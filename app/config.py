from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    upstage_api_key: str
    upstage_base_url: str = "https://api.upstage.ai"
    log_level: str = "INFO"

    # extra="ignore": .env 가 AI 평가용 추가 환경변수(UPSTAGE_API_KEY_2/3 등)와
    # 공유되는 상황에서 strict 검증이 부팅을 막지 않도록 한다.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

from functools import lru_cache
@lru_cache
def get_settings() -> Settings:
    return Settings()