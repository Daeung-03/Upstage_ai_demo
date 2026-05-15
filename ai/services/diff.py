"""약관 버전 간 변경점 요약.

이전 버전의 raw_text 와 신규 버전의 raw_text 를 받아 Solar Pro 3 로 변경점을 비교한다.
정확도 우선 정책 (CLAUDE.md) — `reasoning_effort=high`, `temperature=0`.
"""
from __future__ import annotations

import json
import os
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from ai.prompts.diff import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from ai.services.upstage import UpstageClient

CHAT_COMPLETIONS_PATH = "/chat/completions"
MODEL = "solar-pro3"
DIFF_REASONING_EFFORT = os.getenv("DIFF_REASONING_EFFORT", "high")


class DiffChange(BaseModel):
    category: Literal[
        "pricing", "free_trial", "cancellation", "terms_changes",
        "data_usage", "liability", "disputes", "other",
    ]
    direction: Literal[
        "more_consumer_friendly", "less_consumer_friendly", "neutral"
    ]
    description: str
    risk_level: Literal["high", "medium", "low"]


class DiffResult(BaseModel):
    diff_summary: str
    changes: list[DiffChange] = Field(default_factory=list)


class DiffSchemaError(ValueError):
    """LLM 응답이 DiffResult 스키마를 만족하지 못함."""


async def summarize_version_diff(
    client: UpstageClient,
    *,
    old_text: str,
    new_text: str,
    service_name: str,
) -> DiffResult:
    """두 버전 본문을 비교해 변경점 요약을 생성.

    동일 본문이거나 양쪽 모두 비어있어도 LLM 호출은 한다 (모델이 "변경 없음" 판정).
    호출자에서 raw_text 가 완전히 동일하면 호출 자체를 스킵하는 게 토큰 효율적이지만,
    그건 호출자 책임. 본 함수는 항상 호출.
    """
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(
                    service_name=service_name or "",
                    old_text=old_text or "(이전 버전 본문 없음)",
                    new_text=new_text or "(새 버전 본문 없음)",
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "reasoning_effort": DIFF_REASONING_EFFORT,
    }
    raw = await client.post_json(CHAT_COMPLETIONS_PATH, json=payload)
    content_str = raw["choices"][0]["message"]["content"]
    data = json.loads(content_str)
    try:
        return DiffResult.model_validate(data)
    except ValidationError as e:
        raise DiffSchemaError(f"Diff response validation failed: {e}") from e
