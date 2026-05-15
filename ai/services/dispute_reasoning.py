"""TermClause × 매칭 분쟁 사례 → reasoning 생성.

Solar Pro 3 + reasoning_effort=high (정확도 우선 정책 — CLAUDE.md). Chat 이 아니라
사용자가 분쟁 사례 카드 클릭할 때만 발생하는 호출이고, 결과는 DB 캐시되므로 latency
부담 없음.
"""
from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ai.prompts.dispute_reasoning import (
    CASE_TEMPLATE,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
)
from ai.services.upstage import UpstageClient

CHAT_COMPLETIONS_PATH = "/chat/completions"
MODEL = "solar-pro3"
REASONING_EFFORT = os.getenv("DISPUTE_REASONING_EFFORT", "high")


class ReasoningResult(BaseModel):
    reasoning: str = Field(..., description="3-4문장 자연어 단락")
    user_action: str = Field("", description="사용자가 취할 행동 1-2문장")


class ReasoningSchemaError(ValueError):
    """LLM 응답이 ReasoningResult 형식을 충족하지 못함."""


def _format_cases(matches: list[dict[str, Any]]) -> str:
    """매칭 dict 리스트 → 프롬프트 블록 텍스트."""
    if not matches:
        return "(매칭된 사례 없음)"
    blocks: list[str] = []
    for i, m in enumerate(matches, start=1):
        blocks.append(
            CASE_TEMPLATE.format(
                idx=i,
                title=m.get("title", ""),
                source=m.get("source", ""),
                summary=m.get("summary", ""),
                outcome=m.get("outcome", ""),
                signals=", ".join(m.get("matched_signals") or []) or "(none)",
            )
        )
    return "\n".join(blocks)


async def generate_clause_reasoning(
    client: UpstageClient,
    *,
    clause_title: str | None,
    clause_quote: str | None,
    clause_description: str | None,
    risk_level: str | None,
    pain_point_id: str | None,
    matches: list[dict[str, Any]],
) -> ReasoningResult:
    """단일 TermClause + 매칭 사례 K건 → reasoning 단락 생성."""
    user_msg = USER_PROMPT_TEMPLATE.format(
        clause_title=clause_title or "(제목 없음)",
        risk_level=risk_level or "unknown",
        pain_point_id=pain_point_id or "unknown",
        clause_quote=(clause_quote or "")[:600] or "(원문 없음)",
        clause_description=(clause_description or "")[:400] or "(설명 없음)",
        n=len(matches),
        cases_block=_format_cases(matches),
    )
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "reasoning_effort": REASONING_EFFORT,
    }
    raw = await client.post_json(CHAT_COMPLETIONS_PATH, json=payload)
    content = raw["choices"][0]["message"]["content"]
    data = json.loads(content)
    try:
        return ReasoningResult.model_validate(data)
    except ValidationError as e:
        raise ReasoningSchemaError(f"Reasoning response validation failed: {e}") from e
