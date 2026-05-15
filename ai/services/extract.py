from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from pydantic import ValidationError

from ai.prompts.extract_subscription import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

# Zero-shot baseline용 minimal 시스템 프롬프트 — 사례/도메인 룰 모두 제거.
# `MINIMAL_PROMPT=1` 환경변수 설정 시 활성화. 평가 목적 (시스템 가치 측정) 외엔 사용 안 함.
MINIMAL_SYSTEM_PROMPT = """\
당신은 한국 약관 분석 어시스턴트입니다.
주어진 약관 본문에서 SubscriptionTerms JSON 스키마의 각 필드를 추출하세요.

규칙:
1. 모든 필드는 FieldValue 형식 (value, uncertainty, citation) 으로 채웁니다.
2. value: 약관에 명시된 값. 없거나 모호하면 null.
3. uncertainty: "confirmed" (명시) / "inferred" (유추) / "ambiguous" / "not_specified".
4. citation: confirmed/inferred/ambiguous일 때 page + quote 제공 (quote는 본문 원문 발췌).
5. 응답은 SubscriptionTerms JSON 객체 하나 (response_format=json_schema 강제).
"""

USE_MINIMAL_PROMPT = os.getenv("MINIMAL_PROMPT", "0") == "1"
# AUTO_AI_DOMAIN: AI 도메인으로 감지되면 자동으로 minimal prompt로 분기.
# Round 9 발견 — zero-shot이 우리 OTT-overfit 룰보다 AI 도메인에서 더 잘됨 (-2.9%p).
AUTO_AI_DOMAIN = os.getenv("AUTO_AI_DOMAIN", "1") == "1"

# Round 10: AI 도메인 specialized prompt — minimal base + LLM-1~6 룰만 차용.
# Round 9의 순수 minimal (LLM 룰 0개) 한계 보완: DeepSeek/GPT가 zero-shot 못 따라간 이유는
# 영문 boilerplate 매핑 (binding arbitration, non-refundable 등) 부재. 이걸 다시 살림.
# OTT-overfit 룰 (한국 OTT inferred False, 사례 A-E) 은 *여전히 제외*.
AI_SYSTEM_PROMPT = """\
당신은 한국 약관 분석 어시스턴트입니다.
주어진 약관 본문 (영문 또는 한국어, AI/LLM 서비스 약관일 가능성이 높음) 에서
SubscriptionTerms JSON 스키마의 각 필드를 추출하세요.

규칙:
1. 모든 필드는 FieldValue 형식 (value, uncertainty, citation) 으로 채웁니다.
2. value: 약관에 명시된 값. 없거나 모호하면 null.
3. uncertainty: "confirmed" (명시) / "inferred" (유추) / "ambiguous" / "not_specified".
4. citation: confirmed/inferred/ambiguous일 때 page + quote 제공 (quote는 본문 원문 발췌).
5. 응답은 SubscriptionTerms JSON 객체 하나.

**중요**: 한국 OTT 약관에서 흔한 "침묵=False(inferred)" 룰을 *적용하지 마세요*. AI/LLM
약관은 영미법 개념을 *명시적으로* 사용하므로 명시 부재는 not_specified로 처리.

⚠️ **LLM/AI 약관 추출 룰 (영문 boilerplate 매핑 포함)**:

**(LLM-1) 외부 Pricing Page 위임**:
- "Subscription fees are listed on our Model Pricing Page", "see [pricing page]" 같이 외부 위임이면:
  · pricing.base_price_krw, plan_name = not_specified.
  · pricing.billing_cycle은 본문에 "monthly"/"annually"/"매월" 명시되면 추출, 없으면 not_specified.

**(LLM-2) 학습 데이터 활용**:
- "Inputs and Outputs may be used to improve/train our models", "사용자 입력 학습 활용" 등 명시되면:
  · data_usage.marketing_use = True, "confirmed" (모델 학습은 2차 활용 범주).
  · 옵트아웃 명시 ("unless you opt out", "별도 동의 거부 가능") → data_usage.marketing_consent = "opt_out_available".
  · unfair_clause_flags 에 "AI 학습 데이터 활용" 추가 (한국어 키워드 필수).

**(LLM-3) 한국 거주자 7일 환불권 (Claude consumer §6 패턴)**:
- "Users in [..., South Korea, ...] have 7-day cancellation rights with full refunds" 명시되면:
  · cancellation.notice_period_days = 7, "inferred".
  · cancellation.proration_policy = "prorated", "confirmed".
  · cancellation.method_description에 "한국 거주자: 7일 이내 전액 환불 가능" 명시.

**(LLM-4) 영구 무료 tier — trial 아님**:
- "Free tier", "무료 사용자", "기본 무료 plan"이 *영구 무료*로 등장하면:
  · free_trial.offered = False, "confirmed".
  · 다른 free_trial 필드 = not_specified (False/0 절대 금지).

**(LLM-5) 시간 단위 변환 — days 필드에 hours 직입력 금지**:
- "24 hours before renewal", "24-hour cancellation window":
  · days 필드에는 반올림 day 단위만 (24h → 1).
  · 정확한 시간은 method_description 또는 citation.quote에 명시.
  · **절대 24를 days 필드에 직접 입력하지 말 것**.

**(LLM-6) 영문 boilerplate → 한국 schema 매핑**:
- "IN NO EVENT WILL [COMPANY] BE LIABLE FOR ANY INDIRECT/INCIDENTAL/SPECIAL/CONSEQUENTIAL DAMAGES"
  → liability.indirect_damages_excluded = True, "confirmed".
- "Total aggregate liability ... capped at greater of fees paid in N months or $X"
  → liability.damages_cap_present = True; damages_cap_description에 영문 그대로;
    unfair_clause_flags에 "면책_손배_제한" 추가.
- "All payments are non-refundable except as required by law" / "No refunds":
  → cancellation.proration_policy = "no_refund", "confirmed".
- "Subscriptions auto-renew" / "automatically renews"
  → pricing.auto_renewal_enabled = True, "confirmed".
- "binding arbitration" / "individual arbitration only" / "must be resolved through arbitration"
  → disputes.arbitration_required = True; unfair_clause_flags에 "강제 중재" 추가.
- "waive ... class action" / "no class actions" / "individual basis only"
  → disputes.class_action_waiver = True; unfair_clause_flags에 "집단소송 포기" 추가.
- "California law / Sweden law / PRC law governs"
  → disputes.governing_law에 *영문 표기 그대로*; 한국법 외 외국법이면
    unfair_clause_flags에 "준거법 외국법" 추가.
- "[City], [State] state and federal courts" → disputes.jurisdiction_clause에 영문 그대로.
- **citation.quote는 영문 원문 그대로 (한국어 paraphrase 금지)**.
"""

USE_AI_SPECIALIZED = os.getenv("AI_SPECIALIZED", "1") == "1"  # Round 10 default on

# AI 도메인 keyword: service_name 또는 본문에 존재 시 AI로 판정.
_AI_NAME_KEYWORDS = {
    "claude", "anthropic", "gpt", "openai", "chatgpt",
    "gemini", "google ai", "bard",
    "deepseek", "upstage", "solar",
    "perplexity", "mistral", "llama", "midjourney",
}
_AI_TEXT_KEYWORDS = (
    "Generative AI", "Large Language Model", "model training",
    "AI 어시스턴트", "Inputs and Outputs", "사용자 입력 학습",
    "training data", "AI 학습 데이터", "프롬프트", "Prompts",
)


def _is_ai_domain(service_name: str, parsed_markdown: str | None = None) -> bool:
    """AI 도메인 자동 감지 — service_name keyword 우선, 본문 fallback."""
    name = (service_name or "").lower()
    if any(kw in name for kw in _AI_NAME_KEYWORDS):
        return True
    if parsed_markdown:
        # 본문에 AI 키워드 2개 이상 등장 시 AI로 판정 (단순 언급 거름)
        hit = sum(1 for kw in _AI_TEXT_KEYWORDS if kw in parsed_markdown)
        if hit >= 2:
            return True
    return False


def _detect_language(text: str | None) -> str:
    """약관 본문 언어 감지 — 한글 비율 ≥ 30%면 'ko', 아니면 'en'.

    Round 10 측정: AI_SYSTEM_PROMPT (영문 boilerplate 룰)이 한국어 AI 약관에 부작용
    (-8.5%p) 이라 언어별 분기 필요. Claude 한국어판, Gemini Korea, Upstage 등은
    한국어 본문이라 minimal prompt가 더 효과적 (Round 9).
    """
    if not text:
        return "ko"  # default safe
    ko = sum(1 for c in text if "가" <= c <= "힯")
    total = sum(1 for c in text if c.isalpha())
    if total == 0:
        return "ko"
    return "ko" if ko / total > 0.3 else "en"


def _select_system_prompt(service_name: str, parsed_markdown: str | None = None) -> str:
    """시스템 프롬프트 분기 — MINIMAL_PROMPT > AI 자동 분기 (언어별) > 기본.

    AI 분기 prompt:
    - 영문 AI 약관 (GPT/DeepSeek 영문) → AI_SYSTEM_PROMPT (LLM-1~6 영문 boilerplate 룰).
    - 한국어 AI 약관 (Claude 한국어판/Gemini Korea/Upstage 등) → MINIMAL_SYSTEM_PROMPT.
    - AI_SPECIALIZED=0 환경변수 시 모든 AI를 minimal로 (Round 9 동작).
    """
    if USE_MINIMAL_PROMPT:
        return MINIMAL_SYSTEM_PROMPT
    if AUTO_AI_DOMAIN and _is_ai_domain(service_name, parsed_markdown):
        if USE_AI_SPECIALIZED and _detect_language(parsed_markdown) == "en":
            return AI_SYSTEM_PROMPT
        return MINIMAL_SYSTEM_PROMPT
    return SYSTEM_PROMPT
from ai.schemas.common import Citation, FieldValue
from ai.schemas.subscription import SubscriptionTerms
from ai.services.parse import ParsedElement
from ai.services.upstage import UpstageClient
from ai.services.voting import vote_subscription_terms


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
        if not en:
            continue  # 빈 element 는 "" in qn 이 항상 True 라 첫 element 가 무조건 잡히는 버그 방지
        if qn in en or en in qn:
            return elem

    # 4) 앵커(앞 20자) 매칭 — LLM이 인용 끝을 잘랐을 때
    anchor = qn[:20]
    if len(anchor) >= 8:
        for elem in elements:
            en = _normalize(elem.text)
            if en and anchor in en:
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


def _enrich_with_bbox(terms, elements: list[ParsedElement]):
    """각 섹션의 모든 FieldValue에 대해 citation.bbox를 element 매칭으로 채움.

    Schema-polymorphic — root model의 sub-model 필드를 reflection 으로 순회하므로
    SubscriptionTerms / FinanceTerms / InsuranceTerms 모두에 동작.
    """
    from pydantic import BaseModel

    cls = type(terms)
    for field_name in cls.model_fields:
        section = getattr(terms, field_name)
        if not isinstance(section, BaseModel):
            continue
        section_cls = type(section)
        for inner_name in section_cls.model_fields:
            fv = getattr(section, inner_name)
            if not isinstance(fv, FieldValue):
                continue
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
            {"role": "system", "content": _select_system_prompt(service_name, parsed_markdown)},
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


# ============ Finance / Insurance 도메인 라우팅 ============
#
# OTT 와 달리 도메인 분기 (AUTO_AI_DOMAIN 등) 가 없음 — 호출자가 domain 인자로
# 명시적으로 routing. 프롬프트는 ai/prompts/extract_{finance,insurance}.py 에서 import.
# voting 은 ai/services/voting.vote_terms 가 schema-polymorphic 이라 새 schema 에 그대로 동작.

from ai.prompts.extract_finance import (  # noqa: E402
    SYSTEM_PROMPT as FINANCE_SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE as FINANCE_USER_PROMPT_TEMPLATE,
)
from ai.prompts.extract_insurance import (  # noqa: E402
    SYSTEM_PROMPT as INSURANCE_SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE as INSURANCE_USER_PROMPT_TEMPLATE,
)
from ai.schemas.finance import FinanceTerms  # noqa: E402
from ai.schemas.insurance import InsuranceTerms  # noqa: E402
from ai.services.voting import vote_terms  # noqa: E402


async def _extract_typed(
    client: UpstageClient,
    *,
    schema_cls,
    system_prompt: str,
    user_prompt_template: str,
    parsed_markdown: str,
    parsed_elements: list[ParsedElement],
    service_name: str,
    service_provider: str,
):
    """Generic Solar Pro 3 추출 — schema_cls 의 JSON Schema 로 strict 검증.

    extract_subscription 과 구조는 동일하나 schema/prompt 가 인자화됨. 도메인별
    프롬프트 분기 (AUTO_AI_DOMAIN 등) 는 적용하지 않음 — 호출자가 도메인을 명시.
    """
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": schema_cls.__name__,
            "schema": schema_cls.model_json_schema(),
            "strict": True,
        },
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": user_prompt_template.format(
                    service_name=service_name,
                    service_provider=service_provider,
                    parsed_markdown=parsed_markdown,
                ),
            },
        ],
        "response_format": response_format,
        "reasoning_effort": REASONING_EFFORT,
        "temperature": 0,
    }
    raw = await client.post_json(CHAT_COMPLETIONS_PATH, json=payload)
    content_str = raw["choices"][0]["message"]["content"]
    parsed = json.loads(content_str)
    parsed.setdefault("extraction_date", datetime.now(timezone.utc).isoformat())
    parsed.setdefault("service_name", service_name)
    parsed.setdefault("service_provider", service_provider)
    try:
        terms = schema_cls.model_validate(parsed)
    except ValidationError as e:
        raise SchemaValidationError(
            f"{schema_cls.__name__} response validation failed: {e}"
        ) from e
    return _enrich_with_bbox(terms, parsed_elements)


async def extract_finance(
    client: UpstageClient,
    *,
    parsed_markdown: str,
    parsed_elements: list[ParsedElement],
    service_name: str,
    service_provider: str,
) -> FinanceTerms:
    """전자금융/PG/송금/PFM 도메인 추출. FinanceTerms 반환."""
    return await _extract_typed(
        client,
        schema_cls=FinanceTerms,
        system_prompt=FINANCE_SYSTEM_PROMPT,
        user_prompt_template=FINANCE_USER_PROMPT_TEMPLATE,
        parsed_markdown=parsed_markdown,
        parsed_elements=parsed_elements,
        service_name=service_name,
        service_provider=service_provider,
    )


async def extract_finance_with_voting(
    client: UpstageClient,
    *,
    parsed_markdown: str,
    parsed_elements: list[ParsedElement],
    service_name: str,
    service_provider: str,
    n: int = ENSEMBLE_N,
) -> FinanceTerms:
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    if n == 1:
        return await extract_finance(
            client,
            parsed_markdown=parsed_markdown,
            parsed_elements=parsed_elements,
            service_name=service_name,
            service_provider=service_provider,
        )
    runs: list[FinanceTerms] = []
    for _ in range(n):
        runs.append(await extract_finance(
            client,
            parsed_markdown=parsed_markdown,
            parsed_elements=parsed_elements,
            service_name=service_name,
            service_provider=service_provider,
        ))
    return vote_terms(runs)


async def extract_insurance(
    client: UpstageClient,
    *,
    parsed_markdown: str,
    parsed_elements: list[ParsedElement],
    service_name: str,
    service_provider: str,
) -> InsuranceTerms:
    """보험 도메인 추출. InsuranceTerms 반환."""
    return await _extract_typed(
        client,
        schema_cls=InsuranceTerms,
        system_prompt=INSURANCE_SYSTEM_PROMPT,
        user_prompt_template=INSURANCE_USER_PROMPT_TEMPLATE,
        parsed_markdown=parsed_markdown,
        parsed_elements=parsed_elements,
        service_name=service_name,
        service_provider=service_provider,
    )


async def extract_insurance_with_voting(
    client: UpstageClient,
    *,
    parsed_markdown: str,
    parsed_elements: list[ParsedElement],
    service_name: str,
    service_provider: str,
    n: int = ENSEMBLE_N,
) -> InsuranceTerms:
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    if n == 1:
        return await extract_insurance(
            client,
            parsed_markdown=parsed_markdown,
            parsed_elements=parsed_elements,
            service_name=service_name,
            service_provider=service_provider,
        )
    runs: list[InsuranceTerms] = []
    for _ in range(n):
        runs.append(await extract_insurance(
            client,
            parsed_markdown=parsed_markdown,
            parsed_elements=parsed_elements,
            service_name=service_name,
            service_provider=service_provider,
        ))
    return vote_terms(runs)
