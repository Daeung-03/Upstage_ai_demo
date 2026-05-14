# TODO(groundedness): Upstage 전용 /groundedness-check endpoint가 공식 문서에 추가되면
# CHAT_COMPLETIONS_PATH → 전용 path로 swap, payload를 {context, answer} 단순 형태로 변경.
# 현재는 Solar Pro 3 chat에 verification prompt 보내는 fallback 구현.

from __future__ import annotations

import json
import os

from pydantic import BaseModel, Field

from prompts.groundedness_check import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from services.summarize import KeyClause, SummaryResult
from services.upstage import UpstageClient

CHAT_COMPLETIONS_PATH = "/chat/completions"
MODEL = "solar-pro3"
MIN_SCORE = 0.6  # 의역/요약을 허용하는 prompt에 맞춰 threshold 완화
# verification reasoning_effort. 기본 low (단순 yes/no + score), env로 실험 조절.
GROUND_REASONING_EFFORT = os.getenv("GROUND_REASONING_EFFORT", "medium")
# Default: "medium" — 2026-05-15 Round 5 실험에서 low→medium이 +7%p (C avg 73.3%)
# summarize=high와 결합 시 +8.4%p (BC avg 74.7%, peak 80%)


def _normalize(s: str) -> str:
    return " ".join(s.split())


def _quote_in_source(quote: str, source_markdown: str) -> bool:
    """citation.quote가 source에 (정규화 포함) 포함되는지 deterministic 체크."""
    if not quote or not source_markdown:
        return False
    q = quote.strip()
    if q in source_markdown:
        return True
    qn = _normalize(q)
    sn = _normalize(source_markdown)
    if qn and qn in sn:
        return True
    # 앵커 매칭: 앞부분이 길게 일치하면 LLM이 quote 끝을 잘랐을 가능성
    if len(qn) >= 16 and qn[:16] in sn:
        return True
    return False


class GroundednessResult(BaseModel):
    summary: str
    grounded_clauses: list[KeyClause] = Field(default_factory=list)
    ungrounded_clauses: list[KeyClause] = Field(default_factory=list)
    overall_grounded: bool


async def _check_one(
    client: UpstageClient,
    *,
    context: str,
    answer: str,
) -> tuple[bool, float]:
    """Solar Pro 3 chat completions으로 verification (전용 endpoint 미수록 fallback)."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(context=context, answer=answer),
            },
        ],
        "response_format": {"type": "json_object"},
        "reasoning_effort": GROUND_REASONING_EFFORT,
        "temperature": 0,
    }
    raw = await client.post_json(CHAT_COMPLETIONS_PATH, json=payload)
    content_str = raw["choices"][0]["message"]["content"]
    data = json.loads(content_str)
    # Strict bool 비교 — LLM이 "true"/"false" 문자열을 돌려줘도 ungrounded로 안전하게 처리
    is_grounded = data.get("grounded") is True
    try:
        score = float(data.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    return is_grounded, score


async def check_groundedness(
    client: UpstageClient,
    *,
    summary: SummaryResult,
    source_markdown: str,
) -> GroundednessResult:
    grounded: list[KeyClause] = []
    ungrounded: list[KeyClause] = []
    for clause in summary.key_clauses:
        # 1차: citation.quote가 원문에 있는지 deterministic 체크.
        #      있으면 인용 자체는 검증됨 → 설명만 LLM으로 추가 검증 (의역 허용 prompt 사용).
        quote_anchored = _quote_in_source(clause.citation.quote, source_markdown)
        answer = f'{clause.title}: {clause.description}'
        if quote_anchored:
            answer += f' (원문 인용 확인됨: "{clause.citation.quote}")'
        else:
            answer += f' (원문 인용 미확인: "{clause.citation.quote}")'
        is_grounded, score = await _check_one(client, context=source_markdown, answer=answer)
        # citation이 원문에 anchored이고 LLM이 명백히 모순이라고 안 했으면 (score >= 0.4) 인정
        if quote_anchored and score >= 0.4:
            grounded.append(clause)
        elif is_grounded and score >= MIN_SCORE:
            grounded.append(clause)
        else:
            ungrounded.append(clause)
    # summary 텍스트는 인용 anchor가 없으므로 LLM 판정에만 의존
    summary_is_grounded, summary_score = await _check_one(
        client, context=source_markdown, answer=summary.summary
    )
    summary_grounded = summary_is_grounded and summary_score >= MIN_SCORE
    return GroundednessResult(
        summary=summary.summary,
        grounded_clauses=grounded,
        ungrounded_clauses=ungrounded,
        overall_grounded=(len(ungrounded) == 0 and summary_grounded),
    )
