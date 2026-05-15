from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    upstage_api_key: str
    upstage_api_key_2: str | None = None
    upstage_api_key_3: str | None = None
    upstage_api_key_4: str | None = None
    upstage_base_url: str = "https://api.upstage.ai/v1/"
    log_level: str = "INFO"

    # extra="ignore": .env 가 app 측 DATABASE_URL 등과 공유되더라도 AI Settings 부팅을
    # 막지 않도록. AI Settings 는 Upstage 관련 변수만 검증.
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    @property
    def service_api_key(self) -> str:
        """서비스 dev / FastAPI app / single_run 전용. 항상 key #1.

        평가 스크립트(parallel_run, run_all_fixtures, eval_variance) 가 이 키를
        사용하면 dev 중인 서비스 호출과 quota / rate limit 이 겹친다. 그래서
        분리: key #1 은 서비스만, key 2/3/4 는 평가용.
        """
        return self.upstage_api_key

    @property
    def eval_api_keys(self) -> list[str]:
        """평가 / 벤치마크 스크립트 전용. key #2/3/4 중 설정된 것만.

        비어있으면 호출자가 명시적으로 에러 처리해야 한다 (silent fallback 금지 —
        key #1 으로 빠지면 분리 정책이 무의미해짐).
        """
        return [
            k for k in (self.upstage_api_key_2, self.upstage_api_key_3, self.upstage_api_key_4)
            if k
        ]

    @property
    def app_api_key_pool(self) -> list[str]:
        """FastAPI app 이 round-robin 으로 돌릴 키 풀. key #1 + 설정된 key #2/3/4.

        bulk upload / 데모처럼 동시 요청이 들어올 때 단일 키 rate-limit 에서
        직렬화되는 걸 막기 위해 가용 키를 모두 사용. eval 스크립트가 동시에
        돌면 quota 가 겹칠 수 있으니 그땐 Railway 환경에서 key #2/3/4 를 비워두면
        됨 (→ pool 자동으로 [key #1] 만 됨).
        """
        return [
            k for k in (
                self.upstage_api_key,
                self.upstage_api_key_2,
                self.upstage_api_key_3,
                self.upstage_api_key_4,
            )
            if k
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
