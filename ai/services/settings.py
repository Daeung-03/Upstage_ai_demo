from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    upstage_api_key: str
    upstage_api_key_2: str | None = None
    upstage_api_key_3: str | None = None
    upstage_api_key_4: str | None = None
    upstage_base_url: str = "https://api.upstage.ai/v1"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    @property
    def api_keys(self) -> list[str]:
        keys = [self.upstage_api_key]
        for extra in (self.upstage_api_key_2, self.upstage_api_key_3, self.upstage_api_key_4):
            if extra:
                keys.append(extra)
        return keys


@lru_cache
def get_settings() -> Settings:
    return Settings()
