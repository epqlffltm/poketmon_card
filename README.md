# 포켓몬 카드 중고 시세 API

포켓몬 카드의 중고 시세를 최소가 / 최대가 / 평균가와 변동률로 제공하는 백엔드 API.

시범 대상 5종: 피카츄, 파이리, 꼬부기, 이상해풀, 이브이

## 기술 스택

| 구분 | 사용 기술 |
|---|---|
| 언어 | Python 3.13 |
| 프레임워크 | FastAPI |
| ORM | SQLAlchemy 2.0 (async) |
| DB | PostgreSQL 16 (Docker) |
| 드라이버 | asyncpg |
| 마이그레이션 | Alembic |
| 패키지 관리 | uv |

## 현재 진행 상황

- [x] 프로젝트 초기 설정 (uv, git, .gitignore)
- [x] PostgreSQL 16 Docker 구성 + healthcheck
- [x] 비동기 DB 세션 계층
- [x] 데이터 모델 설계 (card / listing / price_snapshot)
- [x] Alembic 마이그레이션 적용 및 제약 검증
- [ ] 시드 데이터 생성 스크립트
- [ ] 일별 집계 로직
- [ ] 시세 조회 API
- [ ] 프론트엔드

## 실행 방법

```bash
docker compose up -d
uv sync
cp .env.example .env
uv run alembic upgrade head
```

## 데이터 모델

```
card ─┬─< listing         (수집한 개별 매물 원본)
      └─< price_snapshot  (일별 집계 결과)
```

### 설계 결정 1 — 원본과 집계의 분리

매물 원본을 저장하는 `listing`과 일별 집계 결과인 `price_snapshot`을 분리했다.

조회 API는 `price_snapshot`만 읽으므로 매물이 수십만 건 쌓여도 조회 성능이 일정하게 유지된다.
동시에 원본을 보존하므로 이상치 판정 기준을 바꾼 뒤 전체 재집계가 가능하다.
집계값만 저장하는 구조였다면 기준을 변경하는 순간 과거 데이터를 복구할 수 없다.

### 설계 결정 2 — 카드 상태 체계

같은 카드라도 상태에 따라 시세가 크게 달라지므로, 상태를 구분하지 않은 평균값은 의미가 없다.

상태는 두 축으로 나뉜다.

- **미감정(raw)** — `NM / LP / MP / HP / DMG` (TCGPlayer 표준)
- **감정(graded)** — `PSA / BGS / CGC / SGC` 등급 1~10

이 둘은 가격대가 수 배에서 수십 배까지 차이 나는 사실상 다른 상품이므로
하나의 컬럼으로 합치지 않고, `condition` 또는 (`grader`, `grade`) 중
**정확히 하나만** 채워지도록 CHECK 제약으로 강제했다.

미감정 상태 체계로 TCGPlayer 표준을 채택한 이유는, 향후 연동할 외부 시세 API들이
공통적으로 이 체계로 데이터를 제공하기 때문이다. 초기에 맞춰두면 변환 계층과
스키마 마이그레이션이 모두 불필요해진다.

### 설계 결정 3 — NULL 처리

`grader`와 `grade`는 미감정 카드에서 NULL이 된다.
이 때문에 PostgreSQL의 기본 UNIQUE 제약으로는 중복을 막을 수 없다.
표준 SQL에서 NULL은 서로 같지 않은 값으로 취급되어, 동일한 카드·날짜·상태의
스냅샷이 몇 번이든 중복 삽입되기 때문이다.

PostgreSQL 15부터 도입된 `NULLS NOT DISTINCT` 옵션으로 해결했다.

```sql
CREATE UNIQUE INDEX ux_snapshot_variant_date ON price_snapshot
  (card_id, condition, grader, grade, snapshot_date) NULLS NOT DISTINCT;
```

이 제약이 누락되어도 오류가 발생하지 않고 중복 데이터가 조용히 쌓이기 때문에,
마이그레이션 적용 후 실제 데이터를 삽입해 동작을 검증했다.

## 제약 검증

PostgreSQL 16.14 환경에서 실제 INSERT로 확인한 결과.

| 시나리오 | 기대 동작 | 결과 |
|---|---|---|
| 동일 카드·날짜·NM 스냅샷 중복 삽입 | 차단 | `duplicate key value violates unique constraint` |
| `condition`과 `grader` 동시 입력 | 차단 | `violates check constraint ck_snapshot_variant_exclusive` |
| `condition`, `grader` 모두 미입력 | 차단 | `violates check constraint ck_snapshot_variant_exclusive` |
| 동일 카드·날짜의 NM과 PSA 10 | 공존 허용 | 정상 삽입 |

## 앞으로의 설계 방향

### 이상치 처리

중고 매물의 최저가에는 벌크 묶음 판매가, 최고가에는 비정상적인 호가가 섞인다.
따라서 원시 최소·최대값을 그대로 노출하면 시세로서 의미를 갖지 못한다.

`percentile_cont`로 하위 5% ~ 상위 95% 구간을 잘라낸 값을 화면에 노출하고,
절단 이전 값은 별도 컬럼에 보존해 필터 기준 조정의 근거로 사용한다.

평균과 함께 중앙값도 저장한다. 중고 시세는 소수의 극단값에 평균이 크게 흔들리므로
중앙값이 더 안정적인 지표가 된다.

### 변동률 계산

수집 실패나 매물 부재로 특정 날짜의 스냅샷이 비는 상황이 반드시 발생한다.
정확히 N일 전 날짜를 조회하는 방식은 이 경우 값을 얻지 못한다.

기준일 이하의 가장 최근 스냅샷을 이분 탐색으로 찾는 방식으로 처리한다.
단, 대체 조회가 최신 스냅샷 자신을 반환하면 변동률이 항상 0%로 표시되는
오류가 발생하므로 이 경우를 명시적으로 배제한다.

응답의 `null`은 "변동 없음"이 아니라 "비교 가능한 과거 데이터 없음"을 의미하며,
프론트엔드에서 0%와 구분해 표시한다.

## API 설계 (예정)

```
GET /api/v1/cards
GET /api/v1/cards/{card_id}/prices?condition=NM&period=30d
```

응답은 세 부분으로 구성한다.

- `current` — 최신 스냅샷 (최소 / 최대 / 평균 / 중앙값 / 표본 수)
- `change_rates` — 1일 / 7일 / 30일 변동률
- `history` — 차트용 시계열