# app/services/aggregate.py

"""
매물 원본(listing)을 일별 집계(price_snapshot)로 변환한다.

집계는 관계형 대수 그 자체라서 ORM으로 표현하면 오히려 의도가 보이지 않는다.
게다가 여기서 쓰는 percentile_cont / IS NOT DISTINCT FROM / ON CONFLICT 는
모두 PostgreSQL 고유 기능이므로, 이식성을 포기하고 raw SQL로 직접 작성했다.
조회 계층은 ORM을 그대로 사용한다.

build_snapshot_for_date 는 멱등하다.
따라서 배치 재실행과 과거 날짜 백필에 동일한 함수를 쓸 수 있다.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

# 집계는 관계형 대수 그 자체라서 ORM으로 표현하면 오히려 읽기 어려워진다.
# percentile_cont / IS NOT DISTINCT FROM / ON CONFLICT 는 전부 PostgreSQL 고유 기능이므로
# 이식성을 포기하고 raw SQL로 직접 쓴다.
_AGGREGATE_SQL = text(
    """
WITH base AS (
    SELECT card_id, condition, grader, grade, price
    FROM listing
    WHERE is_outlier = false
      AND listed_at >= :start_at
      AND listed_at <  :end_at
),
bounds AS (
    -- percentile_cont 는 ordered-set aggregate 라서 OVER (PARTITION BY) 로 쓸 수 없다.
    -- 따라서 경계를 먼저 구한 뒤 다시 조인하는 2단계 구조가 강제된다.
    SELECT
        card_id, condition, grader, grade,
        count(*)                                              AS n,
        min(price)                                            AS raw_min,
        max(price)                                            AS raw_max,
        percentile_cont(:lo_pct) WITHIN GROUP (ORDER BY price) AS lo,
        percentile_cont(:hi_pct) WITHIN GROUP (ORDER BY price) AS hi
    FROM base
    GROUP BY card_id, condition, grader, grade
),
trimmed AS (
    SELECT b.card_id, b.condition, b.grader, b.grade, b.price,
           bo.raw_min, bo.raw_max
    FROM base b
    JOIN bounds bo
      -- JOIN ... USING / = 는 NULL = NULL 을 false 로 판정한다.
      -- graded 컬럼이 NULL 인 raw 행이 통째로 사라지므로 IS NOT DISTINCT FROM 이 필수다.
      ON  b.card_id   =                    bo.card_id
      AND b.condition IS NOT DISTINCT FROM bo.condition
      AND b.grader    IS NOT DISTINCT FROM bo.grader
      AND b.grade     IS NOT DISTINCT FROM bo.grade
    -- 표본이 적으면 퍼센타일 절단이 오히려 데이터를 왜곡하므로 통과시킨다.
    WHERE bo.n < :min_samples
       OR (b.price >= bo.lo AND b.price <= bo.hi)
)
INSERT INTO price_snapshot (
    card_id, condition, grader, grade, snapshot_date,
    raw_min_price, raw_max_price,
    min_price, max_price, avg_price, median_price, sample_count
)
SELECT
    card_id, condition, grader, grade, :snapshot_date,
    raw_min, raw_max,
    min(price),
    max(price),
    round(avg(price), 2),
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY price)::numeric, 2),
    count(*)
FROM trimmed
GROUP BY card_id, condition, grader, grade, raw_min, raw_max
ON CONFLICT (card_id, condition, grader, grade, snapshot_date)
DO UPDATE SET
    raw_min_price = EXCLUDED.raw_min_price,
    raw_max_price = EXCLUDED.raw_max_price,
    min_price     = EXCLUDED.min_price,
    max_price     = EXCLUDED.max_price,
    avg_price     = EXCLUDED.avg_price,
    median_price  = EXCLUDED.median_price,
    sample_count  = EXCLUDED.sample_count
"""
)


async def build_snapshot_for_date(session: AsyncSession, target: date) -> int:
    """target 날짜에 올라온 매물을 집계해 price_snapshot 을 upsert 한다.

    멱등하므로 배치 재실행이나 과거 날짜 백필에 그대로 쓸 수 있다.
    """
    start_at = datetime.combine(target, time.min, tzinfo=timezone.utc)
    end_at = start_at + timedelta(days=1)

    result = await session.execute(
        _AGGREGATE_SQL,
        {
            "start_at": start_at,
            "end_at": end_at,
            "snapshot_date": target,
            "lo_pct": settings.outlier_lower_percentile,
            "hi_pct": settings.outlier_upper_percentile,
            "min_samples": settings.min_samples_for_trimming,
        },
    )
    await session.commit()
    return result.rowcount or 0


async def backfill(session: AsyncSession, start: date, end: date) -> int:
    total = 0
    cursor = start
    while cursor <= end:
        total += await build_snapshot_for_date(session, cursor)
        cursor += timedelta(days=1)
    return total