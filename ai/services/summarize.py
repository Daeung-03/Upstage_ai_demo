from __future__ import annotations

import json
import os

from pydantic import BaseModel, Field

from ai.prompts.summarize_subscription import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from ai.schemas.subscription import SubscriptionTerms  # noqa: F401 (re-export for callers)
from ai.services.upstage import UpstageClient

CHAT_COMPLETIONS_PATH = "/chat/completions"
MODEL = "solar-pro3"
# summary 단계 reasoning_effort. 미지정 시 Solar default(`minimal`).
# 위험 조항 식별은 도메인 판단이 들어가 high까지 올릴 수 있음. env로 실험 조절.
SUMMARIZE_REASONING_EFFORT = os.getenv("SUMMARIZE_REASONING_EFFORT", "high")
# Default: "high" — 2026-05-15 Round 5 실험에서 minimal→high가 +4.7%p (B avg 71%)
# ground=medium과 결합 시 +8.4%p (BC avg 74.7%, peak 80%)


class KeyClauseCitation(BaseModel):
    page: int
    quote: str


class KeyClause(BaseModel):
    title: str
    description: str
    risk_level: str  # "high" | "medium" | "low"
    pain_point_id: str
    citation: KeyClauseCitation
    # v1.1: LLM 이 직접 카테고리 출력. enum 값 (PAYMENT/CANCELLATION/PRIVACY/RENEWAL/
    # LIABILITY/TERMS_CHANGE/ETC). 미지정/빈 문자열 시 term_service._derive_clause_type
    # 이 pain_point_id + title 키워드 기반으로 자동 추론 → backwards-compat.
    clause_type: str = ""


class SummaryResult(BaseModel):
    summary: str
    key_clauses: list[KeyClause] = Field(default_factory=list)


async def summarize_risks(client: UpstageClient, *, terms: BaseModel) -> SummaryResult:
    """약관 추출 결과를 요약 — schema-agnostic. SubscriptionTerms / FinanceTerms /
    InsuranceTerms 어떤 BaseModel 이든 JSON dump 해 LLM 에 넘긴다. 도메인별 프롬프트
    튜닝은 follow-up (ai/EXPERIMENTS.md 백로그)."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(terms_json=terms.model_dump_json(indent=2)),
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "reasoning_effort": SUMMARIZE_REASONING_EFFORT,
    }
    raw = await client.post_json(CHAT_COMPLETIONS_PATH, json=payload)
    content_str = raw["choices"][0]["message"]["content"]
    data = json.loads(content_str)
    return SummaryResult.model_validate(data)
