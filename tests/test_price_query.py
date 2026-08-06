# tests/test_price_query.py

"""
변동률 계산 단위 테스트.

compute_change_rates 는 DB에 의존하지 않는 순수 함수이므로
PostgreSQL 없이 경계 조건을 직접 검증할 수 있다.

여기서 다루는 상황들은 실제 데이터로 재현하기가 오히려 어렵다.
스냅샷이 정확히 1건인 경우, 평균가가 0인 경우 등은
운영 데이터에서 우연히 발생하기를 기다릴 수 없기 때문이다.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.price_query import compute_change_rates

TODAY = date(2026, 8, 6)


def snap(day_offset: int, avg: float | int) -> SimpleNamespace:
    """PriceSnapshot 대역.

    compute_change_rates 는 snapshot_date 와 avg_price 만 참조하므로
    실제 모델 인스턴스 대신 최소한의 객체로 충분하다.
    """
    return SimpleNamespace(
        snapshot_date=TODAY - timedelta(days=day_offset),
        avg_price=Decimal(str(avg)),
    )


class TestEmptyResults:
    """비교 대상이 없으면 0% 가 아니라 None 이어야 한다."""

    def test_스냅샷이_없으면_전부_None(self):
        rates = compute_change_rates([])
        assert rates == {"1d": None, "7d": None, "30d": None}

    def test_스냅샷이_하나뿐이면_전부_None(self):
        """fallback 이 자기 자신을 참조하면 변동률이 항상 0% 가 된다.

        오류가 발생하지 않아 발견하기 어려운 종류의 버그이므로
        명시적으로 None 을 반환하는지 확인한다.
        """
        rates = compute_change_rates([snap(0, 10_000)])
        assert all(v is None for v in rates.values())

    def test_기준가가_0이면_None(self):
        """0으로 나누기를 예외 대신 None 으로 처리한다."""
        rates = compute_change_rates([snap(7, 0), snap(0, 11_000)])
        assert rates["7d"] is None


class TestChangeRate:
    def test_상승률_계산(self):
        rates = compute_change_rates([snap(7, 10_000), snap(0, 11_000)])
        assert rates["7d"].rate == Decimal("10.00")

    def test_하락률은_음수(self):
        rates = compute_change_rates([snap(7, 10_000), snap(0, 8_000)])
        assert rates["7d"].rate == Decimal("-20.00")

    def test_소수점_둘째자리로_반올림(self):
        rates = compute_change_rates([snap(7, 3), snap(0, 4)])
        assert rates["7d"].rate == Decimal("33.33")

    def test_기준_날짜와_기준가를_함께_반환(self):
        """숫자만으로는 어느 시점과 비교했는지 알 수 없다."""
        rates = compute_change_rates([snap(7, 10_000), snap(0, 11_000)])
        result = rates["7d"]
        assert result.base_date == TODAY - timedelta(days=7)
        assert result.base_price == Decimal("10000")


class TestFallback:
    """빈 날짜가 있을 때 가장 가까운 이전 스냅샷으로 내려앉는지."""

    def test_정확한_날짜가_없으면_이전_값_사용(self):
        # 7일 전은 비어 있고 9일 전만 존재한다
        rates = compute_change_rates([snap(9, 10_000), snap(0, 11_000)])
        assert rates["7d"] is not None
        assert rates["7d"].base_date == TODAY - timedelta(days=9)

    def test_기준일_이후_스냅샷은_참조하지_않는다(self):
        """5일 전 데이터가 있어도 7일 변동률은 그것을 쓰면 안 된다."""
        rates = compute_change_rates([snap(9, 10_000), snap(5, 20_000), snap(0, 11_000)])
        assert rates["7d"].base_date == TODAY - timedelta(days=9)

    def test_모든_구간이_같은_스냅샷을_참조할_수_있다(self):
        """45일 전 데이터 하나뿐이면 1일 변동률도 그것을 참조한다.

        논리적으로 올바른 동작이지만 오해를 부를 수 있어
        base_date 를 함께 노출하는 근거가 된다.
        """
        rates = compute_change_rates([snap(45, 8_000), snap(0, 11_000)])
        base_dates = {r.base_date for r in rates.values() if r}
        assert len(base_dates) == 1

    def test_가장_오래된_스냅샷보다_이전_구간은_None(self):
        """3일치 데이터만 있으면 30일 변동률은 계산할 수 없다."""
        rates = compute_change_rates([snap(3, 10_000), snap(0, 11_000)])
        assert rates["1d"] is not None
        assert rates["30d"] is None


@pytest.mark.parametrize(
    ("past", "current", "expected"),
    [
        (10_000, 10_000, "0.00"),
        (10_000, 20_000, "100.00"),
        (20_000, 10_000, "-50.00"),
        (10_000, 1, "-99.99"),
    ],
)
def test_변동률_경계값(past, current, expected):
    rates = compute_change_rates([snap(7, past), snap(0, current)])
    assert rates["7d"].rate == Decimal(expected)
