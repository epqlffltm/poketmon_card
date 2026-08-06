# app/main.py

"""
FastAPI 애플리케이션 진입점.

라우터 등록, 정적 파일 서빙, 헬스체크만 담당하고 실제 로직은 각 계층에 위임한다.

실행:
    uv run uvicorn app.main:app --reload
"""

from pathlib import Path

from fastapi import FastAPI, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.cards import router as cards_router

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(
    title="포켓몬 카드 중고 시세 API",
    description="카드별 중고 시세를 최소/최대/평균가와 변동률로 제공한다.",
    version="0.1.0",
)

app.include_router(cards_router, prefix="/api/v1")

# 프론트엔드를 같은 오리진에서 서빙해 CORS 설정을 불필요하게 만든다.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", status_code=status.HTTP_200_OK, include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", status_code=status.HTTP_200_OK, tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}