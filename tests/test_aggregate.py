# tests/test_aggregate.py

"""
집계 로직 통합 테스트.

실제 PostgreSQL 에 연결해 검증한다.
퍼센타일 절단, NULL 조인, upsert 멱등성은 모두 DB 엔진의 동작에 의존하므로
mock 으로는 의미 있는 검증이 불가능하다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.price import Grader, Listing, PriceSnapshot, RawCondition
from app.services.aggregate import build_snapshot_for_date

TARGET = date(2026, 8, 6)


def listing(card_id: int, price: int, *, condition=RawCondition.NM, seq: int = 0):
    return Listing(
        card_id=card_id,
        source="test",
        external_id=f"t-{condition.value}-{seq}-{price}",
        condition=condition,
        price=Decimal(price),
        listed_at=datetime.combine(TARGET, time(12, 0), tzinfo=UTC),
    )


async def snapshots_of(session, card_id: int) -> list[PriceSnapshot]:
    stmt = select(PriceSnapshot).where(PriceSnapshot.card_id == card_id)
    return list((await session.scalars(stmt)).all())


class TestBasicAggregation:
    async def test_매물이_없으면_스냅샷도_없다(self, session, card):
        count = await build_snapshot_for_date(session, TARGET)
        assert count == 0
        assert await snapshots_of(session, card.id) == []

    async def test_평균과_중앙값을_계산한다(self, session, card):
        # 표본이 적어 절단이 적용되지 않는 구간
        for i, price in enumerate([10_000, 20_000, 30_000]):
            session.add(listing(card.id, price, seq=i))
        await session.commit()

        await build_snapshot_for_date(session, TARGET)
        snap = (await snapshots_of(session, card.id))[0]

        assert snap.avg_price == Decimal("20000.00")
        assert snap.median_price == Decimal("20000.00")
        assert snap.sample_count == 3

    async def test_다른_날짜의_매물은_포함하지_않는다(self, session, card):
        session.add(listing(card.id, 10_000, seq=1))
        other = listing(card.id, 999_000, seq=2)
        other.listed_at = datetime.combine(date(2026, 8, 5), time(12, 0), tzinfo=UTC)
        session.add(other)
        await session.commit()

        await build_snapshot_for_date(session, TARGET)
        snap = (await snapshots_of(session, card.id))[0]
        assert snap.sample_count == 1

    async def test_이상치로_표시된_매물은_제외된다(self, session, card):
        session.add(listing(card.id, 10_000, seq=1))
        flagged = listing(card.id, 999_000, seq=2)
        flagged.is_outlier = True
        session.add(flagged)
        await session.commit()

        await build_snapshot_for_date(session, TARGET)
        snap = (await snapshots_of(session, card.id))[0]
        assert snap.sample_count == 1
        assert snap.raw_max_price == Decimal("10000.00")


class TestPercentileTrimming:
    async def test_표본이_적으면_절단하지_않는다(self, session, card):
        """min_samples_for_trimming 미만이면 극단값도 그대로 둔다."""
        prices = [10_000, 10_000, 500_000]
        assert len(prices) < settings.min_samples_for_trimming

        for i, p in enumerate(prices):
            session.add(listing(card.id, p, seq=i))
        await session.commit()

        await build_snapshot_for_date(session, TARGET)
        snap = (await snapshots_of(session, card.id))[0]
        assert snap.max_price == Decimal("500000.00")
        assert snap.sample_count == 3

    async def test_표본이_충분하면_극단값을_잘라낸다(self, session, card):
        # 정상 매물 20건 + 벌크 1건 + 과대 호가 1건
        prices = [40_000] * 20 + [1_000, 900_000]
        for i, p in enumerate(prices):
            session.add(listing(card.id, p, seq=i))
        await session.commit()

        await build_snapshot_for_date(session, TARGET)
        snap = (await snapshots_of(session, card.id))[0]

        # 원본은 극단값을 보존한다
        assert snap.raw_min_price == Decimal("1000.00")
        assert snap.raw_max_price == Decimal("900000.00")
        # 노출값에서는 제거된다
        assert snap.min_price == Decimal("40000.00")
        assert snap.max_price == Decimal("40000.00")
        assert snap.sample_count == 20


class TestNullJoin:
    """미감정 매물은 grader/grade 가 NULL 이다.

    조인에서 = 를 쓰면 이 행들이 오류 없이 전부 사라진다.
    IS NOT DISTINCT FROM 이 실제로 이를 막는지 확인한다.
    """

    async def test_미감정_매물이_집계에서_누락되지_않는다(self, session, card):
        for i, p in enumerate([10_000, 20_000]):
            session.add(listing(card.id, p, seq=i))
        await session.commit()

        await build_snapshot_for_date(session, TARGET)
        snaps = await snapshots_of(session, card.id)

        assert len(snaps) == 1
        assert snaps[0].sample_count == 2
        assert snaps[0].grader is None

    async def test_상태별로_별도_스냅샷이_생성된다(self, session, card):
        session.add(listing(card.id, 40_000, condition=RawCondition.NM, seq=1))
        session.add(listing(card.id, 20_000, condition=RawCondition.MP, seq=2))
        await session.commit()

        await build_snapshot_for_date(session, TARGET)
        snaps = await snapshots_of(session, card.id)

        assert len(snaps) == 2
        by_condition = {s.condition: s.avg_price for s in snaps}
        assert by_condition[RawCondition.NM] == Decimal("40000.00")
        assert by_condition[RawCondition.MP] == Decimal("20000.00")

    async def test_감정카드는_미감정과_별도로_집계된다(self, session, card):
        session.add(listing(card.id, 40_000, seq=1))
        graded = Listing(
            card_id=card.id,
            source="test",
            external_id="graded-1",
            grader=Grader.PSA,
            grade=Decimal("10"),
            price=Decimal(500_000),
            listed_at=datetime.combine(TARGET, time(12, 0), tzinfo=UTC),
        )
        session.add(graded)
        await session.commit()

        await build_snapshot_for_date(session, TARGET)
        snaps = await snapshots_of(session, card.id)

        assert len(snaps) == 2
        raw = next(s for s in snaps if s.grader is None)
        psa = next(s for s in snaps if s.grader is Grader.PSA)
        assert raw.avg_price == Decimal("40000.00")
        assert psa.avg_price == Decimal("500000.00")


class TestIdempotency:
    async def test_두_번_실행해도_중복되지_않는다(self, session, card):
        session.add(listing(card.id, 10_000, seq=1))
        await session.commit()

        await build_snapshot_for_date(session, TARGET)
        await build_snapshot_for_date(session, TARGET)

        assert len(await snapshots_of(session, card.id)) == 1

    async def test_재실행_시_최신_매물을_반영한다(self, session, card):
        session.add(listing(card.id, 10_000, seq=1))
        await session.commit()
        await build_snapshot_for_date(session, TARGET)

        session.add(listing(card.id, 30_000, seq=2))
        await session.commit()
        await build_snapshot_for_date(session, TARGET)

        snaps = await snapshots_of(session, card.id)
        assert len(snaps) == 1
        assert snaps[0].avg_price == Decimal("20000.00")
        assert snaps[0].sample_count == 2


class TestConstraints:
    async def test_동일_조합_중복_삽입이_차단된다(self, session, card):
        """NULLS NOT DISTINCT 가 없으면 grader/grade 가 NULL 이라 중복이 통과한다."""
        from sqlalchemy.exc import IntegrityError

        def make():
            return PriceSnapshot(
                card_id=card.id,
                condition=RawCondition.NM,
                snapshot_date=TARGET,
                raw_min_price=Decimal(100),
                raw_max_price=Decimal(900),
                min_price=Decimal(200),
                max_price=Decimal(800),
                avg_price=Decimal(500),
                median_price=Decimal(480),
                sample_count=10,
            )

        session.add(make())
        await session.commit()

        session.add(make())
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
