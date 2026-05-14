import os
from pathlib import Path

import pytest

from services.pipeline import run_pipeline
from services.settings import Settings
from services.upstage import UpstageClient

FIXTURE_DIR = Path(__file__).parent.parent.parent / "data" / "fixtures"


def _skip_if_no_key():
    if not os.getenv("UPSTAGE_API_KEY"):
        pytest.skip("UPSTAGE_API_KEY not set")


def _skip_if_no_fixture(name: str) -> Path:
    path = FIXTURE_DIR / name
    if not path.exists():
        pytest.skip(f"fixture {name} not found at {path}")
    return path


@pytest.mark.e2e
async def test_netflix_terms_end_to_end():
    _skip_if_no_key()
    fixture = _skip_if_no_fixture("netflix_terms.pdf")

    settings = Settings()
    async with UpstageClient(settings) as client:
        result = await run_pipeline(
            client,
            file_bytes=fixture.read_bytes(),
            filename=fixture.name,
            service_name="Netflix",
            service_provider="Netflix, Inc.",
        )

    assert result.terms.service_name == "Netflix"
    assert result.terms.pricing.base_price_krw.value is not None
    assert result.summary
    assert len(result.key_clauses) >= 1
    print("\n=== Netflix E2E Result ===")
    print(f"Summary: {result.summary}")
    print(f"Grounded: {result.grounded}")
    print("Key clauses:")
    for c in result.key_clauses:
        print(f"  - [{c.risk_level}] {c.title}: {c.description}")
    print("Timings:", [(t.stage, round(t.seconds, 2)) for t in result.timings])
