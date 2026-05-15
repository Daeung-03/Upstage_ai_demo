import pytest


@pytest.fixture
def sample_api_key() -> str:
    return "test-api-key-not-real"


@pytest.fixture
def sample_base_url() -> str:
    return "https://api.upstage.test/v1"
