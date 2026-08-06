# app/schemas/price.py

"""
API 응답 스키마.

SQLAlchemy 모델과 별도로 두는 이유는 세 가지다.

    1. 노출 통제  - id, created_at 같은 내부 컬럼을 클라이언트에 드러내지 않는다.
                    DB 구조와 API 계약이 서로 독립적으로 변경될 수 있게 된다.
    2. 구조 재조립 - current / change_rates / history 형태는 어느 테이블에도
                    그대로 존재하지 않는다. 서비스 계층 계산 결과를 담을 그릇이 필요하다.
    3. 자동 문서화 - FastAPI가 이 모델로 OpenAPI 스펙과 /docs 예시를 생성한다.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.price import RawCondition


class CardSummary(BaseModel):
    """카드 기본 정보."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    pokedex_number: int
    name_ko: str
    name_en: str
    set_code: str
    card_number: str
    rarity: str | None
    image_url: str | None


class PricePoint(BaseModel):
    """차트용 시계열 한 점."""

    model_config = ConfigDict(from_attributes=True)

    snapshot_date: date
    min_price: Decimal
    max_price: Decimal
    avg_price: Decimal
    median_price: Decimal
    sample_count: int


class CurrentPrice(BaseModel):
    """최신 스냅샷."""

    model_config = ConfigDict(from_attributes=True)

    snapshot_date: date

    # 퍼센타일 절단을 거친 값. 화면에 노출하는 것은 이쪽이다.
    min_price: Decimal
    max_price: Decimal
    avg_price: Decimal
    median_price: Decimal

    # 절단 전 원본. 표본이 적을 때 화면값을 얼마나 신뢰할지 판단하는 근거가 된다.
    raw_min_price: Decimal
    raw_max_price: Decimal

    # 이 값이 작으면 시세로서 신뢰도가 낮다. 클라이언트에서 함께 표시하는 것을 전제한다.
    sample_count: int


class ChangeRate(BaseModel):
    """단일 구간의 변동률.

    base_date 를 함께 내려주는 이유는, 빈 날짜가 많은 구간에서는
    요청한 기간과 실제 비교 대상 날짜가 어긋날 수 있기 때문이다.
    예를 들어 45일 전 스냅샷 하나만 존재하면 '1일 변동률'도 그 값을 참조한다.
    숫자만 내려주면 클라이언트가 이 상황을 구분할 방법이 없다.
    """

    model_config = ConfigDict(from_attributes=True)

    rate: Decimal = Field(description="변동률(%). 양수면 상승.")
    base_date: date = Field(description="실제로 비교 기준이 된 스냅샷 날짜")
    base_price: Decimal = Field(description="기준 시점의 평균가")


class ChangeRates(BaseModel):
    """구간별 변동률.

    각 필드의 null 은 '변동 없음'이 아니라 '비교 가능한 과거 데이터 없음'이다.
    클라이언트에서 0% 와 반드시 구분해 표시해야 한다.
    """

    day_1: ChangeRate | None = None
    day_7: ChangeRate | None = None
    day_30: ChangeRate | None = None


class CardPriceResponse(BaseModel):
    """시세 조회 최종 응답."""

    card: CardSummary
    condition: RawCondition
    current: CurrentPrice | None = Field(default=None, description="스냅샷이 하나도 없으면 null")
    change_rates: ChangeRates
    history: list[PricePoint]
