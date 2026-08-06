# app/main.py

"""
FastAPI 애플리케이션 진입점.

라우터 등록과 헬스체크만 담당하고, 실제 로직은 각 계층에 위임한다.

실행:
    uv run uvicorn app.main:app --reload
"""

from fastapi import FastAPI, status

from app.api.v1.cards import router as cards_router

app = FastAPI(
    title="포켓몬 카드 중고 시세 API",
    description="카드별 중고 시세를 최소/최대/평균가와 변동률로 제공한다.",
    version="0.1.0",
)

app.include_router(cards_router, prefix="/api/v1")


@app.get("/health", status_code=status.HTTP_200_OK, tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}