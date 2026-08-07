# app/core/logging.py

"""
애플리케이션 로깅 설정.

출력 형식을 두 가지로 나눈다.

    개발  - 사람이 읽기 좋은 한 줄 형식
    배포  - JSON 한 줄. 컨테이너 로그는 결국 수집 도구가 파싱하므로
            구조화되어 있어야 필드별 검색과 집계가 가능하다.

요청 ID를 ContextVar 에 담아 같은 요청에서 발생한 모든 로그를 묶는다.
로거를 함수마다 넘기지 않아도 되고, async 환경에서 요청별로 격리된다.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

# 요청 단위로 격리되는 저장소. 스레드가 아니라 async 태스크 기준으로 동작한다.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# uvicorn 이 이미 출력하는 접근 로그와 중복되지 않도록 사용할 이름
LOGGER_NAME = "pokecard"


class RequestIdFilter(logging.Filter):
    """모든 로그 레코드에 현재 요청 ID를 붙인다."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """로그 레코드를 JSON 한 줄로 직렬화한다."""

    # LogRecord 기본 속성. 이 외의 것만 추가 필드로 취급한다.
    _RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__)

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }

        # logger.info("...", extra={"card_id": 1}) 로 넘긴 값을 그대로 담는다
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and key not in payload:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(*, level: str = "INFO", json_format: bool = False) -> None:
    """루트 로거를 구성한다. 앱 시작 시 한 번만 호출한다."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())

    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s  %(levelname)-7s [%(request_id)s] %(name)s  %(message)s",
                datefmt="%H:%M:%S",
            )
        )

    root = logging.getLogger()
    # reload 로 여러 번 호출되어도 핸들러가 누적되지 않게 한다
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # SQLAlchemy 엔진 로그는 echo_sql 설정으로만 켠다.
    # 여기서 INFO 로 두면 모든 쿼리가 출력되어 다른 로그를 덮는다.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str = LOGGER_NAME) -> logging.Logger:
    return logging.getLogger(name)