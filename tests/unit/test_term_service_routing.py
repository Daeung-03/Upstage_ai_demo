"""process_upload 의 도메인 라우팅 회귀 테스트.

버그: process_upload 가 run_full_pipeline 에 domain 을 안 넘겨, 보험/금융
약관까지 항상 subscription(OTT) 추출기로 처리됐다 (clause 가 OTT 로 매핑).
수정 후: vendor/폼 domain → 파이프라인 도메인으로 매핑해 전달.
"""
from __future__ import annotations

import uuid

import pytest

from app.services import ai_client, term_service


@pytest.mark.parametrize("service_name,form_domain,expected", [
    # vendor 매핑 우선 — carrot → INSURANCE → insurance 추출기
    ("캐롯 해외여행보험", "INSURANCE", "insurance"),
    # vendor 매핑 — kakao-pay → FINANCE → finance 추출기
    ("카카오페이", "FINANCE", "finance"),
    # OTT → subscription
    ("Netflix", "OTT", "subscription"),
    # vendor 미매칭 + 전용 추출기 없는 도메인 → subscription fallback
    ("이름없는서비스", "ETC", "subscription"),
])
async def test_process_upload_routes_pipeline_domain(
    monkeypatch, service_name, form_domain, expected
):
    """process_upload 가 run_full_pipeline 에 올바른 파이프라인 도메인을 넘긴다."""
    captured: dict = {}

    async def fake_pipeline(**kwargs):
        captured["domain"] = kwargs.get("domain")
        # 라우팅만 확인하면 되므로 파이프라인 본체는 건너뛴다.
        raise RuntimeError("stop-after-routing")

    monkeypatch.setattr(ai_client, "run_full_pipeline", fake_pipeline)

    with pytest.raises(RuntimeError, match="stop-after-routing"):
        await term_service.process_upload(
            db=None,
            user_id=uuid.uuid4(),
            service_name=service_name,
            subscribed_at=None,
            file_bytes=b"%PDF-fake",
            file_url="/files/x.pdf",
            domain=form_domain,
        )

    assert captured["domain"] == expected
