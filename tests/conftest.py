# tests/conftest.py

"""
DB 통합 테스트용 픽스처.

집계 로직은 percentile_cont, IS NOT DISTINCT FROM, ON CONFLICT 등
PostgreSQL 고유 기능에 의존하므로 SQLite 로 대체할 수 없다.
mock 으로 감싸면 정작 검증하려는 SQL 동작이 테스트에서 사라지기 때문에
실제 PostgreSQL 에 연결한다.

운영 DB 를 오염시키지 않도록 별도의 테스트 DB 를 만들어 사용하고,
각 테스트 전에 테이블을 비워 서로 간섭하지 않게 한다.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from urllib.parse import urlparse

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.base import Base

TEST_DB_SUFFIX = "_test"


def _test_database_url() -> str:
    """운영 DB 이름 뒤에 _test 를 붙인 URL."""
    url = settings.database_url
    base, _, name = url.rpartition("/")
    return f"{base}/{name}{TEST_DB_SUFFIX}"


async def _ensure_test_database() -> None:
    """테스트 DB 가 없으면 생성한다.

    CREATE DATABASE 는 트랜잭션 안에서 실행할 수 없어
    SQLAlchemy 엔진 대신 asyncpg 로 직접 연결한다.
    """
    parsed = urlparse(settings.database_url.replace("postgresql+asyncpg", "postgresql"))
    target = parsed.path.lstrip("/") + TEST_DB_SUFFIX

    conn = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 5432,
        database="postgres",
    )
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", target
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{target}"')
    finally:
        await conn.close()


@pytest_asyncio.fixture(scope="session")
async def engine():
    await _ensure_test_database()
    # NullPool: 테스트 간 커넥션 재사용으로 인한 상태 오염을 막는다
    eng = create_async_engine(_test_database_url(), poolclass=NullPool)

    async with eng.begin() as conn:
        # 마이그레이션 대신 메타데이터로 직접 생성한다.
        # 테스트의 관심사는 마이그레이션 이력이 아니라 최종 스키마이기 때문이다.
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    """테스트마다 빈 테이블 상태로 시작한다.

    집계 함수가 내부에서 commit 을 호출하므로 트랜잭션 롤백으로는 격리할 수 없다.
    대신 매 테스트 시작 시 TRUNCATE 로 초기화한다.
    RESTART IDENTITY 를 붙여 시퀀스도 되돌려야 card.id 를 예측할 수 있다.
    """
    maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with maker() as sess:
        await sess.execute(text("TRUNCATE card RESTART IDENTITY CASCADE"))
        await sess.commit()
        yield sess


@pytest_asyncio.fixture
async def card(session):
    """테스트용 카드 1종."""
    from app.models.card import Card

    item = Card(
        pokedex_number=25,
        name_ko="피카츄",
        name_en="Pikachu",
        set_code="base1",
        card_number="58",
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item