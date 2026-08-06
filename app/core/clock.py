# app/core/clock.py

"""
시간 기준을 UTC로 통일한다.

date.today() 는 실행 환경의 로컬 타임존을 따른다.
반면 listing.listed_at 은 timestamptz 이고 집계는 UTC 자정을 하루 경계로 삼는다.

두 기준이 어긋나면 시차만큼의 구간에서 잘못된 날짜를 조회하게 된다.
예를 들어 KST(UTC+9) 환경에서는 오전 0시부터 9시 사이에
date.today() 가 UTC 기준보다 하루 앞선 값을 반환한다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime


def utc_today() -> date:
    """UTC 기준 오늘 날짜."""
    return datetime.now(UTC).date()


def utc_now() -> datetime:
    """UTC 기준 현재 시각."""
    return datetime.now(UTC)
