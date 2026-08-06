# app/api/v1/cards.py

"""
카드 및 시세 조회 엔드포인트.

조회 구간과 응답 구간이 다르다는 점에 주의.
30일 변동률을 계산하려면 30일 전 스냅샷이 필요하므로,
사용자가 period=7d 를 요청해도 내부적으로는 30일 이상을 조회해야 한다.
이를 맞추지 않으면 period=7d 일 때 day_30 이 항상 null 이 된다.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utc_today
from app.db.session import get_session
from app.models.card import Card
from app.models.price import RawCondition
from app.schemas.price import (
    CardPriceResponse,
    CardSummary,
    ChangeRate,
    ChangeRates,
    CurrentPrice,
    PricePoint,
)
from app.services.price_query import (
    CHANGE_WINDOWS,
    PERIOD_DAYS,
    compute_change_rates,
    fetch_history,
)

router = APIRouter(prefix="/cards", tags=["cards"])


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=list[CardSummary],
    summary="카드 목록",
)
async def list_cards(session: AsyncSession = Depends(get_session)) -> list[Card]:
    stmt = select(Card).order_by(Card.pokedex_number)
    return list((await session.scalars(stmt)).all())


@router.get(
    "/{card_id}/prices",
    status_code=status.HTTP_200_OK,
    response_model=CardPriceResponse,
    summary="카드 시세 조회",
)
async def get_card_prices(
    card_id: int,
    condition: RawCondition = Query(default=RawCondition.NM, description="카드 상태 등급"),
    period: Literal["7d", "30d", "90d"] = Query(default="30d", description="history 에 담을 기간"),
    session: AsyncSession = Depends(get_session),
) -> CardPriceResponse:
    card = await session.get(Card, card_id)
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="card not found")

    # 변동률 계산에 필요한 만큼 넉넉히 조회한다.
    # 빈 날짜 fallback 때문에 기준일보다 더 과거를 참조할 수 있으므로 여유분을 둔다.
    lookback = max(PERIOD_DAYS[period], max(CHANGE_WINDOWS.values())) + 14
    snapshots = await fetch_history(
        session, card_id, condition, utc_today() - timedelta(days=lookback)
    )

    rates = compute_change_rates(snapshots)

    # 응답에 담을 구간은 사용자가 요청한 period 만큼만 잘라낸다.
    visible_from = utc_today() - timedelta(days=PERIOD_DAYS[period])
    history = [s for s in snapshots if s.snapshot_date >= visible_from]

    def to_rate(label: str) -> ChangeRate | None:
        value = rates.get(label)
        return ChangeRate.model_validate(value) if value else None

    return CardPriceResponse(
        card=CardSummary.model_validate(card),
        condition=condition,
        current=CurrentPrice.model_validate(snapshots[-1]) if snapshots else None,
        change_rates=ChangeRates(
            day_1=to_rate("1d"),
            day_7=to_rate("7d"),
            day_30=to_rate("30d"),
        ),
        history=[PricePoint.model_validate(s) for s in history],
    )
