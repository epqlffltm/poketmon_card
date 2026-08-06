# app/db/session.py

"""
비동기 엔진과 세션 팩토리를 생성하고, FastAPI 의존성 주입용 get_session을 제공한다.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# pool_pre_ping: 도커 DB 재시작 후 풀에 남은 죽은 커넥션을 걸러낸다
engine = create_async_engine(
    settings.database_url, echo=settings.echo_sql, pool_pre_ping=True
)

# expire_on_commit=False: commit 후 속성 접근 시 재조회를 시도하는데,
# async 컨텍스트에서는 이게 MissingGreenlet 예외로 터진다
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session