import os

# app.config.Settings 가 import 시점에 검증된다. test 환경에서 실제 DB 없이도
# import 가 통과하도록 collect 직전에 placeholder 를 주입.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("UPSTAGE_API_KEY", "test-api-key-not-real")

import pytest  # noqa: E402


@pytest.fixture
def sample_api_key() -> str:
    return "test-api-key-not-real"


@pytest.fixture
def sample_base_url() -> str:
    return "https://api.upstage.test/v1"
