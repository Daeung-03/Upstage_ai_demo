from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    upstage_api_key: str
    log_level: str = "INFO"

    class Config:
        env_file = ".env"

from functools import lru_cache
@lru_cache
def get_settings() -> Settings:
    return Settings()