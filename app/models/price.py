# app/models/price.py

"""
시세 관련 모델 2종.

    Listing       - 수집한 개별 매물 원본. 집계하지 않고 그대로 쌓기만 한다.
    PriceSnapshot - 일별 집계 결과. 조회 API는 이 테이블만 읽는다.

미감정 상태(condition)와 감정 등급(grader + grade)은 서로 배타적이며,
둘 중 정확히 하나만 채워지도록 CHECK 제약으로 강제한다.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RawCondition(str, enum.Enum):
    """TCGPlayer 표준 미감정 카드 상태. 외부 API가 이 taxonomy로 주므로 그대로 사용."""

    NM = "NM"  # Near Mint
    LP = "LP"  # Lightly Played
    MP = "MP"  # Moderately Played
    HP = "HP"  # Heavily Played
    DMG = "DMG"  # Damaged


class Grader(str, enum.Enum):
    PSA = "PSA"
    BGS = "BGS"
    CGC = "CGC"
    SGC = "SGC"


# raw / graded 는 서로 배타적이어야 한다는 제약을 두 테이블에서 공유한다.
_VARIANT_CHECK = (
    "(condition IS NOT NULL AND grader IS NULL AND grade IS NULL) "
    "OR (condition IS NULL AND grader IS NOT NULL AND grade IS NOT NULL)"
)


class Listing(Base):
    """수집한 개별 매물 원본. 절대 여기서 집계하지 않고 그대로 쌓기만 한다."""

    __tablename__ = "listing"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("card.id", ondelete="CASCADE"), nullable=False, index=True
    )

    source: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    condition: Mapped[RawCondition | None] = mapped_column(
        SAEnum(RawCondition, name="raw_condition"), nullable=True
    )
    grader: Mapped[Grader | None] = mapped_column(SAEnum(Grader, name="grader"), nullable=True)
    grade: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)

    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="KRW")

    # 집계 시 제외할 매물(벌크 묶음, 장난 매물 등)을 배치가 표시한다.
    is_outlier: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    listed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    card: Mapped["Card"] = relationship(back_populates="listings")  # noqa: F821

    __table_args__ = (
        CheckConstraint(_VARIANT_CHECK, name="ck_listing_variant_exclusive"),
        CheckConstraint("price > 0", name="ck_listing_price_positive"),
        # 같은 매물 재수집 시 중복 방지
        UniqueConstraint("source", "external_id", name="uq_listing_source_external"),
        Index("ix_listing_card_listed_at", "card_id", "listed_at"),
    )


class PriceSnapshot(Base):
    """일별 집계 결과. 조회 API는 이 테이블만 읽는다."""

    __tablename__ = "price_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("card.id", ondelete="CASCADE"), nullable=False)

    condition: Mapped[RawCondition | None] = mapped_column(
        SAEnum(RawCondition, name="raw_condition"), nullable=True
    )
    grader: Mapped[Grader | None] = mapped_column(SAEnum(Grader, name="grader"), nullable=True)
    grade: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)

    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)

    # 이상치를 자르지 않은 원본값. 필터 튜닝의 근거로 남겨둔다.
    raw_min_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    raw_max_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    # 화면에 노출할 값. p05~p95로 자른 구간.
    min_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    max_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    avg_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # 중고 시세는 median이 avg보다 훨씬 안정적이라 반드시 같이 저장한다.
    median_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    card: Mapped["Card"] = relationship(back_populates="snapshots")  # noqa: F821

    __table_args__ = (
        CheckConstraint(_VARIANT_CHECK, name="ck_snapshot_variant_exclusive"),
        CheckConstraint("sample_count > 0", name="ck_snapshot_sample_positive"),
        CheckConstraint("min_price <= max_price", name="ck_snapshot_min_le_max"),
        # PostgreSQL 기본 UNIQUE는 NULL을 서로 다른 값으로 취급해서 중복이 뚫린다.
        # graded 컬럼이 NULL인 raw 스냅샷을 막으려면 NULLS NOT DISTINCT 필수 (PG 15+).
        Index(
            "ux_snapshot_variant_date",
            "card_id",
            "condition",
            "grader",
            "grade",
            "snapshot_date",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_snapshot_card_date", "card_id", "snapshot_date"),
    )
