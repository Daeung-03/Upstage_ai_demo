from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    upstage_api_key: str
    log_level: str = "INFO"

    # extra="ignore": .env 가 AI 평가용 추가 환경변수(UPSTAGE_API_KEY_2/3,
    # UPSTAGE_BASE_URL 등)와 공유되는 상황에서 strict 검증이 부팅을 막지 않도록.
    # upstage_base_url 은 ai/services/settings.Settings 가 단일 소스로 보유 —
    # 실제 HTTP 호출 경로는 그쪽만 사용하므로 app.config 에 중복 둘 필요 없음.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

from functools import lru_cache
@lru_cache
def get_settings() -> Settings:
    return Settings()