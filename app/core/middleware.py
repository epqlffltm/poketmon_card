# app/core/middleware.py

"""
요청 로깅 미들웨어와 예외 핸들러.

미들웨어는 요청마다 ID를 발급해 ContextVar 에 넣고, 처리 시간과 상태 코드를 기록한다.
발급한 ID는 응답 헤더(X-Request-ID)로도 내려주므로
사용자가 오류를 신고할 때 해당 요청의 로그를 바로 찾을 수 있다.

예외 핸들러를 두는 이유는 처리되지 않은 예외가 스택트레이스째 응답에 실리는 것을 막기 위함이다.
내부 구조와 파일 경로가 그대로 노출되므로, 상세 내용은 로그에만 남기고
클라이언트에는 요청 ID만 전달한다.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_logger, request_id_var

logger = get_logger()


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or request_id_var.get() or "-"


# 정적 파일과 헬스체크는 로그를 남기지 않는다.
# 페이지 한 번 여는 데 요청이 수십 건 발생해 실제 API 로그가 묻힌다.
_SKIP_PREFIXES = ("/static", "/health", "/favicon.ico")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # 클라이언트가 보낸 ID가 있으면 이어받아 분산 추적을 가능하게 한다
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        token = request_id_var.set(request_id)
        # 예외 핸들러는 이 미들웨어 바깥에서 실행되어 ContextVar 가 이미 초기화된 상태다.
        # 요청 객체에 함께 담아두면 스코프와 무관하게 접근할 수 있다.
        request.state.request_id = request_id

        skip = request.url.path.startswith(_SKIP_PREFIXES)
        started = time.perf_counter()

        # ContextVar 초기화는 로깅 이후여야 한다.
        # finally 는 try 블록을 벗어날 때 실행되므로, 그 안에서 reset 하면
        # 로그에 요청 ID가 이미 사라진 상태가 된다.
        try:
            try:
                response = await call_next(request)
            except Exception:
                elapsed = (time.perf_counter() - started) * 1000
                # exc_info 를 포함해 스택트레이스를 로그에만 남긴다
                logger.exception(
                    "요청 처리 중 예외",
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "duration_ms": round(elapsed, 1),
                    },
                )
                raise

            elapsed = (time.perf_counter() - started) * 1000
            response.headers["X-Request-ID"] = request_id

            if not skip:
                logger.info(
                    "%s %s %s %.1fms",
                    request.method,
                    request.url.path,
                    response.status_code,
                    elapsed,
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code,
                        "duration_ms": round(elapsed, 1),
                    },
                )
            return response
        finally:
            request_id_var.reset(token)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(SQLAlchemyError)
    async def handle_db_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception(
            "데이터베이스 오류",
            extra={"path": request.url.path, "request_id": _request_id(request)},
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": "일시적으로 데이터를 조회할 수 없습니다.",
                "request_id": _request_id(request),
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # 미들웨어에서 이미 로그를 남겼으므로 여기서는 응답 형태만 정리한다
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "서버 오류가 발생했습니다.",
                "request_id": _request_id(request),
            },
        )