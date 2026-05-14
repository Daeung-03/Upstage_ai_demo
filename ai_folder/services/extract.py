from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from pydantic import ValidationError

from prompts.extract_subscription import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from schemas.common import Citation, FieldValue
from schemas.subscription import SubscriptionTerms
from services.parse import ParsedElement
from services.upstage import UpstageClient
from services.voting import vote_subscription_terms


class SchemaValidationError(ValueError):
    """추출된 응답이 SubscriptionTerms 스키마에 맞지 않을 때.

    ValueError를 상속해 기존 `pytest.raises(ValueError, match="validation")` 호환.
    """


ENSEMBLE_N = int(os.getenv("EXTRACT_ENSEMBLE_N", "2"))
# Default: N=2 + medium — 23-run 실험(2026-05-14) 결과 G config(N=2 medium)이 평균 71.6%로 winner.
# N=3 medium(65.8%) 대비 +5.8%p, 시간 -28%, 토큰 -24%.
# N=2 voting은 N=3 대비 절반 비용으로 비슷한 정확도. medium reasoning이 sweet spot
# (high는 reasoning 경로가 다양해 voting과 충돌, low는 45%로 망함).
REASONING_EFFORT = os.getenv("EXTRACT_REASONING_EFFORT", "medium")

CHAT_COMPLETIONS_PATH = "/chat/completions"
MODEL = "solar-pro3"
SECTION_NAMES = (
    "pricing", "free_trial", "cancellation", "terms_changes",
    "data_usage", "liability", "disputes",
)


def _normalize(s: str) -> str:
    """공백/줄바꿈 정규화 — 따옴표 발췌가 element.text와 줄바꿈/공백만 다를 때 매칭되도록."""
    return " ".join(s.split())


def _find_element_for_quote(
    quote: str, page: int, elements: list[ParsedElement]
) -> ParsedElement | None:
    """quote를 element.text에 매칭. 다단계 fallback:
    1) page 우선 정확 substring
    2) 전 페이지 정확 substring
    3) 정규화(공백 통일) 후 substring (양방향)
    4) quote 앞 20자 앵커가 element.text에 들어있으면 매칭 (LLM이 끝부분을 잘랐을 때)
    """
    if not quote:
        return None
    q = quote.strip()

    # 1) page 우선 정확
    for elem in elements:
        if elem.page == page and q in elem.text:
            return elem
    # 2) 전체 정확
    for elem in elements:
        if q in elem.text:
            return elem

    # 3) 정규화 후 양방향 substring
    qn = _normalize(q)
    if not qn:
        return None
    for elem in elements:
        en = _normalize(elem.text)
        if qn in en or en in qn:
            return elem

    # 4) 앵커(앞 20자) 매칭 — LLM이 인용 끝을 잘랐을 때
    anchor = qn[:20]
    if len(anchor) >= 8:
        for elem in elements:
            if anchor in _normalize(elem.text):
                return elem

    return None


def _enrich_citation(
    citation: Citation | None, elements: list[ParsedElement]
) -> Citation | None:
    if citation is None or citation.bbox is not None:
        return citation
    elem = _find_element_for_quote(citation.quote, citation.page, elements)
    if elem is None:
        return citation
    updates: dict = {"bbox": elem.bbox}
    if citation.section is None:
        updates["section"] = elem.category
    return citation.model_copy(update=updates)


def _enrich_with_bbox(
    terms: SubscriptionTerms, elements: list[ParsedElement]
) -> SubscriptionTerms:
    """각 섹션의 모든 FieldValue에 대해 citation.bbox를 element 매칭으로 채움."""
    for section_name in SECTION_NAMES:
        section = getattr(terms, section_name)
        for field_name in section.__class__.model_fields:
            fv: FieldValue = getattr(section, field_name)
            new_citation = _enrich_citation(fv.citation, elements)
            if new_citation is not fv.citation:
                fv.citation = new_citation
    return terms


async def extract_subscription(
    client: UpstageClient,
    *,
    parsed_markdown: str,
    parsed_elements: list[ParsedElement],
    service_name: str,
    service_provider: str,
) -> SubscriptionTerms:
    """Solar Pro 3 chat completions + json_schema로 SubscriptionTerms 추출.

    Information Extract API는 nested 스키마 미지원이라 chat completions 사용.
    citation.bbox는 Document Parse elements와 quote 매칭으로 후처리에서 채워짐.
    """
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "SubscriptionTerms",
            "schema": SubscriptionTerms.model_json_schema(),
            "strict": True,
        },
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(
                    service_name=service_name,
                    service_provider=service_provider,
                    parsed_markdown=parsed_markdown,
                ),
            },
        ],
        "response_format": response_format,
        "reasoning_effort": REASONING_EFFORT,  # env로 조절 (실험용)
        "temperature": 0,  # 추출은 결정론적으로 (Solar는 완전 결정적이진 않지만 variance 최소화)
    }
    raw = await client.post_json(CHAT_COMPLETIONS_PATH, json=payload)
    content_str = raw["choices"][0]["message"]["content"]
    parsed = json.loads(content_str)
    parsed.setdefault("extraction_date", datetime.now(timezone.utc).isoformat())
    parsed.setdefault("service_name", service_name)
    parsed.setdefault("service_provider", service_provider)
    try:
        terms = SubscriptionTerms.model_validate(parsed)
    except ValidationError as e:
        raise SchemaValidationError(f"Extract response validation failed: {e}") from e
    return _enrich_with_bbox(terms, parsed_elements)


async def extract_subscription_with_voting(
    client: UpstageClient,
    *,
    parsed_markdown: str,
    parsed_elements: list[ParsedElement],
    service_name: str,
    service_provider: str,
    n: int = ENSEMBLE_N,
) -> SubscriptionTerms:
    """N회 sequential extract → majority voting.

    병렬은 Upstage 429 rate limit에 걸려 순차 호출. n=1이면 voting 생략.
    citation은 winning value를 가진 run에서 가져오므로 bbox 보존됨.
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    if n == 1:
        return await extract_subscription(
            client,
            parsed_markdown=parsed_markdown,
            parsed_elements=parsed_elements,
            service_name=service_name,
            service_provider=service_provider,
        )

    runs: list[SubscriptionTerms] = []
    for _ in range(n):
        terms = await extract_subscription(
            client,
            parsed_markdown=parsed_markdown,
            parsed_elements=parsed_elements,
            service_name=service_name,
            service_provider=service_provider,
        )
        runs.append(terms)
    return vote_subscription_terms(runs)
