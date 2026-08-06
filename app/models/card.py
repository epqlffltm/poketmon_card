# app/models/card.py

"""
카드 마스터 테이블. 포켓몬 1종이 아니라 '세트+번호로 특정되는 카드 1종'이 단위다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Card(Base):
    __tablename__ = "card"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 포켓몬 도감 번호 (피카츄 25, 파이리 4, 꼬부기 7, 이상해풀 2, 이브이 133)
    pokedex_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name_ko: Mapped[str] = mapped_column(String(64), nullable=False)
    name_en: Mapped[str] = mapped_column(String(64), nullable=False)

    # 같은 포켓몬이라도 세트/번호가 다르면 완전히 다른 카드, 다른 시세다
    set_code: Mapped[str] = mapped_column(String(32), nullable=False)
    card_number: Mapped[str] = mapped_column(String(16), nullable=False)
    rarity: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 이미지는 직접 호스팅하지 않고 공식 소스 URL을 참조만 한다
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    listings: Mapped[list["Listing"]] = relationship(  # noqa: F821
        back_populates="card", cascade="all, delete-orphan"
    )
    snapshots: Mapped[list["PriceSnapshot"]] = relationship(  # noqa: F821
        back_populates="card", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("set_code", "card_number", name="uq_card_set_number"),
    )