# app/scripts/seed.py

"""
개발용 더미 데이터 생성 스크립트.

카드 5종과 60일치 매물(listing)을 삽입한 뒤, 전체 기간을 집계해 스냅샷을 만든다.

의도적으로 '지저분한' 데이터를 만든다.
깨끗한 데이터로는 이상치 필터와 변동률 fallback이 실제로 동작하는지 검증할 수 없기 때문이다.

    - 일부 날짜는 매물을 통째로 비운다      -> 변동률 fallback 경로 검증용
    - 일부 매물은 비정상적으로 싸거나 비싸다 -> 퍼센타일 절단 검증용

실행:
    uv run python -m app.scripts.seed
"""

from __future__ import annotations

import asyncio
import random
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select

from app.db.session import AsyncSessionLocal
from app.models.card import Card
from app.models.price import Listing, PriceSnapshot, RawCondition
from app.services.aggregate import backfill

# 실행할 때마다 같은 데이터가 나오도록 고정한다.
# 집계 결과를 눈으로 비교하며 디버깅하려면 재현 가능해야 한다.
random.seed(20260806)

DAYS = 60
SOURCES = ["bunjang", "joongna", "danggeun"]

# (도감번호, 한글명, 영문명, 세트코드, 카드번호, 레어도, NM 기준가)
CARDS: list[tuple[int, str, str, str, str, str, int]] = [
    (25, "피카츄", "Pikachu", "base1", "58", "Common", 42_000),
    (4, "파이리", "Charmander", "base1", "46", "Common", 28_000),
    (7, "꼬부기", "Squirtle", "base1", "63", "Common", 25_000),
    (2, "이상해풀", "Ivysaur", "base1", "30", "Uncommon", 33_000),
    (133, "이브이", "Eevee", "base2", "51", "Common", 38_000),
]

# 상태별 가격 배율. NM 대비 얼마나 떨어지는지.
CONDITION_MULTIPLIER: dict[RawCondition, float] = {
    RawCondition.NM: 1.00,
    RawCondition.LP: 0.78,
    RawCondition.MP: 0.55,
    RawCondition.HP: 0.35,
    RawCondition.DMG: 0.18,
}

# 하루 전체가 비어버릴 확률 (수집 실패 / 매물 부재 재현)
EMPTY_DAY_RATE = 0.08
# 벌크 묶음이 개별 카드로 잘못 등록된 매물
BULK_RATE = 0.03
# 장난이거나 협상 여지를 크게 둔 과대 호가
OVERPRICED_RATE = 0.02


async def seed_cards(session) -> list[Card]:
    """카드 마스터를 삽입한다. 이미 있으면 재사용한다."""
    existing = list((await session.scalars(select(Card))).all())
    if existing:
        print(f"카드 {len(existing)}종 이미 존재, 재사용")
        return existing

    cards = [
        Card(
            pokedex_number=dex,
            name_ko=name_ko,
            name_en=name_en,
            set_code=set_code,
            card_number=card_number,
            rarity=rarity,
            # 이미지는 직접 호스팅하지 않고 공식 소스를 참조만 한다
            image_url=f"https://images.pokemontcg.io/{set_code}/{card_number}.png",
        )
        for dex, name_ko, name_en, set_code, card_number, rarity, _ in CARDS
    ]
    session.add_all(cards)
    await session.commit()
    for card in cards:
        await session.refresh(card)

    print(f"카드 {len(cards)}종 삽입")
    return cards


def _generate_price(center: float) -> float:
    """중심가 주변의 매물 가격 하나를 만든다.

    정규분포 대신 로그정규분포를 쓴다.
    가격은 음수가 될 수 없고, 실제 분포도 오른쪽으로 꼬리가 긴 형태이기 때문이다.
    """
    price = center * random.lognormvariate(0, 0.12)

    roll = random.random()
    if roll < BULK_RATE:
        price *= random.uniform(0.15, 0.30)
    elif roll < BULK_RATE + OVERPRICED_RATE:
        price *= random.uniform(4, 12)

    return price


async def seed_listings(session, cards: list[Card]) -> int:
    """60일치 매물을 생성한다."""
    await session.execute(delete(Listing))
    await session.commit()

    today = date.today()
    rows: list[Listing] = []
    empty_days = 0
    seq = 0

    for card, (*_, base_price) in zip(cards, CARDS, strict=True):
        # 카드마다 다른 추세를 준다 (하루 -0.4% ~ +0.5%)
        drift = random.uniform(-0.004, 0.005)
        level = float(base_price)

        for offset in range(DAYS, -1, -1):
            day = today - timedelta(days=offset)
            # 랜덤워크: 추세 + 일별 변동
            level *= 1 + drift + random.gauss(0, 0.018)

            if random.random() < EMPTY_DAY_RATE:
                empty_days += 1
                continue

            for condition, multiplier in CONDITION_MULTIPLIER.items():
                # 상태가 나쁠수록 매물 자체가 드물다
                count = max(0, int(random.gauss(12 * multiplier, 3)))
                center = level * multiplier

                for _ in range(count):
                    seq += 1
                    price = _generate_price(center)

                    rows.append(
                        Listing(
                            card_id=card.id,
                            source=random.choice(SOURCES),
                            external_id=f"seed-{seq}",
                            condition=condition,
                            price=Decimal(str(round(price, -2))),
                            currency="KRW",
                            listed_at=datetime.combine(
                                day,
                                time(
                                    hour=random.randrange(24),
                                    minute=random.randrange(60),
                                ),
                                tzinfo=timezone.utc,
                            ),
                        )
                    )

    session.add_all(rows)
    await session.commit()

    print(f"매물 {len(rows)}건 삽입 (빈 날짜 {empty_days}일)")
    return len(rows)


async def report(session) -> None:
    """삽입 결과를 요약해 출력한다. 집계 로직 검증의 기준선이 된다."""
    stmt = (
        select(
            Card.name_ko,
            Listing.condition,
            func.count().label("n"),
            func.min(Listing.price).label("min"),
            func.max(Listing.price).label("max"),
            func.round(func.avg(Listing.price)).label("avg"),
        )
        .join(Listing, Listing.card_id == Card.id)
        .where(Listing.condition == RawCondition.NM)
        .group_by(Card.name_ko, Listing.condition)
        .order_by(Card.name_ko)
    )
    rows = (await session.execute(stmt)).all()

    print("\nNM 상태 기준 요약 (절단 전 원본)")
    print(f"{'카드':<10} {'건수':>6} {'최소':>10} {'최대':>12} {'평균':>10}")
    for name, _, n, lo, hi, avg in rows:
        print(f"{name:<10} {n:>6} {lo:>10,.0f} {hi:>12,.0f} {avg:>10,.0f}")
    print("\n최소/최대가 평균에서 크게 벗어나 있다면 이상치가 제대로 섞인 것이다.")


async def build_snapshots(session) -> int:
    """삽입한 매물 전 기간을 집계한다."""
    await session.execute(delete(PriceSnapshot))
    await session.commit()

    today = date.today()
    made = await backfill(session, today - timedelta(days=DAYS), today)
    print(f"스냅샷 {made}건 생성")
    return made


async def main() -> None:
    async with AsyncSessionLocal() as session:
        cards = await seed_cards(session)
        await seed_listings(session, cards)
        await build_snapshots(session)
        await report(session)


if __name__ == "__main__":
    asyncio.run(main())