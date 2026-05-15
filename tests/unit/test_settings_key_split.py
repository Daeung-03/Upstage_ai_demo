"""Settings 의 key 분리 정책 단위 테스트.

key #1 = service_api_key (서비스 dev 전용)
key 2/3/4 = eval_api_keys (평가 스크립트 전용)
"""
import pytest

from ai.services.settings import Settings


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """.env 파일에 UPSTAGE_API_KEY_* 가 set 되어 있어 explicit kwargs 만으로는
    test 환경 격리가 안 됨. env 를 명시적으로 비우고 매 테스트가 자기 값을 넣는다.
    """
    for var in ("UPSTAGE_API_KEY", "UPSTAGE_API_KEY_2",
                "UPSTAGE_API_KEY_3", "UPSTAGE_API_KEY_4"):
        monkeypatch.delenv(var, raising=False)


def _make(**kwargs) -> Settings:
    """env_file 비활성화 + 명시 kwargs 만으로 Settings 구성."""
    return Settings(_env_file=None, **kwargs)


def test_service_api_key_returns_key_1():
    s = _make(
        upstage_api_key="key1",
        upstage_api_key_2="key2",
        upstage_api_key_3="key3",
        upstage_api_key_4="key4",
    )
    assert s.service_api_key == "key1"


def test_eval_api_keys_excludes_key_1():
    """eval_api_keys 는 절대 key #1 을 포함하지 않는다 (분리 정책의 핵심)."""
    s = _make(
        upstage_api_key="key1",
        upstage_api_key_2="key2",
        upstage_api_key_3="key3",
        upstage_api_key_4="key4",
    )
    assert s.eval_api_keys == ["key2", "key3", "key4"]
    assert "key1" not in s.eval_api_keys


def test_eval_api_keys_skips_unset():
    """key 2/3/4 중 일부만 set 되어도 그것만 리턴."""
    s = _make(
        upstage_api_key="key1",
        upstage_api_key_2="key2",
        upstage_api_key_4="key4",
    )
    assert s.eval_api_keys == ["key2", "key4"]


def test_eval_api_keys_empty_when_only_key_1_set():
    """key #1 만 있고 나머지는 None → eval_api_keys 빈 리스트.

    호출자(평가 스크립트)가 이 빈 리스트를 보고 명시적으로 exit 해야 함.
    Settings 단에선 fallback 금지.
    """
    s = _make(upstage_api_key="key1")
    assert s.eval_api_keys == []
    # service 키는 여전히 살아있음
    assert s.service_api_key == "key1"
