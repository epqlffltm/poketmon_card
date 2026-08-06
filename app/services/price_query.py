# app/services/price_query.py

"""
스냅샷 조회와 변동률 계산.

변동률의 핵심 난점은 '정확히 N일 전 스냅샷이 존재하지 않는다'는 것이다.
수집 실패나 매물 부재로 특정 날짜가 통째로 비는 일은 반드시 발생한다.
따라서 기준일과 정확히 일치하는 행을 찾는 대신,
기준일 이하의 가장 최근 스냅샷으로 내려앉히는(fallback) 방식을 쓴다.

compute_change_rates 는 DB에 의존하지 않는 순수 함수다.
덕분에 컨테이너 없이 단위 테스트로 경계 조건을 검증할 수 있다.
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import date, timedelta
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.price import PriceSnapshot, RawCondition

# 변동률을 계산할 기준 구간
CHANGE_WINDOWS: dict[str, int] = {"1d": 1, "7d": 7, "30d": 30}

PERIOD_DAYS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90}


async def fetch_history(
    session: AsyncSession,
    card_id: int,
    condition: RawCondition,
    since: date,
) -> list[PriceSnapshot]:
    """오래된 순으로 정렬된 스냅샷 목록."""
    stmt = (
        select(PriceSnapshot)
        .where(
            PriceSnapshot.card_id == card_id,
            PriceSnapshot.condition == condition,
            PriceSnapshot.grader.is_(None),
            PriceSnapshot.snapshot_date >= since,
        )
        .order_by(PriceSnapshot.snapshot_date)
    )
    return list((await session.scalars(stmt)).all())


def _snapshot_on_or_before(
    snapshots: list[PriceSnapshot], dates: list[date], target: date
) -> PriceSnapshot | None:
    """target 이하의 가장 최근 스냅샷.

    수집 실패나 매물 0건으로 특정 날짜가 통째로 비는 일이 반드시 생긴다.
    정확히 그 날짜를 찾으면 None 이 되어버리므로 '가장 가까운 이전 값'으로 내려앉힌다.
    """
    idx = bisect_right(dates, target) - 1
    return snapshots[idx] if idx >= 0 else None


class ChangeRate(NamedTuple):
    """변동률과 그것을 계산할 때 실제로 참조한 스냅샷 날짜.

    base_date 를 함께 반환하는 이유는, 빈 날짜가 많으면
    45일 전 스냅샷으로 '1일 변동률'이 계산되는 상황이 실제로 가능하기 때문이다.
    숫자만 내려주면 클라이언트가 이를 구분할 방법이 없다.
    """

    rate: Decimal
    base_date: date
    base_price: Decimal


def compute_change_rates(
    snapshots: list[PriceSnapshot],
) -> dict[str, ChangeRate | None]:
    """기준가 대비 변동률(%). 비교 대상이 없으면 None.

    None 은 '변동 없음'이 아니라 '비교 가능한 과거 데이터 없음'을 뜻한다.
    """
    if not snapshots:
        return {label: None for label in CHANGE_WINDOWS}

    dates = [s.snapshot_date for s in snapshots]
    latest = snapshots[-1]
    rates: dict[str, ChangeRate | None] = {}

    for label, days in CHANGE_WINDOWS.items():
        target = latest.snapshot_date - timedelta(days=days)
        past = _snapshot_on_or_before(snapshots, dates, target)

        # fallback 이 자기 자신을 집어오면 변동률이 항상 0% 로 나온다.
        # 오류가 발생하지 않아 발견하기 어려운 종류의 버그이므로 명시적으로 배제한다.
        if past is None or past.snapshot_date >= latest.snapshot_date:
            rates[label] = None
            continue
        if not past.avg_price:
            rates[label] = None
            continue

        delta = (latest.avg_price - past.avg_price) / past.avg_price * 100
        rates[label] = ChangeRate(
            rate=delta.quantize(Decimal("0.01")),
            base_date=past.snapshot_date,
            base_price=past.avg_price,
        )

    return rates
