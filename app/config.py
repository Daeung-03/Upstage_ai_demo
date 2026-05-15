from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    upstage_api_key: str
    upstage_base_url: str = "https://api.upstage.ai"
    log_level: str = "INFO"

    class Config:
        env_file = ".env"

from functools import lru_cache
@lru_cache
def get_settings() -> Settings:
    return Settings()