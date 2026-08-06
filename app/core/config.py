# app/core/config.py

"""
.env 기반 애플리케이션 설정. 전역 settings 싱글턴을 제공한다.
집계 시 사용할 이상치 절단 기준도 여기서 관리해 코드 수정 없이 조정할 수 있게 했다.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://poke:poke@localhost:5432/pokecard"
    echo_sql: bool = False

    # 집계 시 화면 노출용 min/max를 자를 퍼센타일 구간
    outlier_lower_percentile: float = 0.05
    outlier_upper_percentile: float = 0.95
    # 표본이 이보다 적으면 퍼센타일 절단이 오히려 왜곡이라 건너뛴다
    min_samples_for_trimming: int = 8


settings = Settings()
