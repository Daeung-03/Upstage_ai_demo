"""약관 버전 간 변경점 요약.

이전 버전의 raw_text 와 신규 버전의 raw_text 를 받아 Solar Pro 3 로 변경점을 비교한다.
정확도 우선 정책 (CLAUDE.md) — `reasoning_effort=high`, `temperature=0`.
"""
from __future__ import annotations

import json
import math
import os
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from ai.prompts.diff import (
    SYSTEM_PROMPT,
    USER_IMPACT_SYSTEM_PROMPT,
    USER_IMPACT_USER_PROMPT_TEMPLATE,
    USER_PROMPT_TEMPLATE,
)
from ai.services.embed import embed_passages
from ai.services.upstage import UpstageClient

CHAT_COMPLETIONS_PATH = "/chat/completions"
MODEL = "solar-pro3"
DIFF_REASONING_EFFORT = os.getenv("DIFF_REASONING_EFFORT", "high")


_CATEGORY_VALUES = {
    "pricing", "free_trial", "cancellation", "terms_changes",
    "data_usage", "liability", "disputes", "other",
}
_DIRECTION_VALUES = {"more_consumer_friendly", "less_consumer_friendly", "neutral"}
_RISK_VALUES = {"high", "medium", "low"}


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

    # LLM 이 enum 밖 값을 환각하는 경우 (예: category="account") 호출 전체를
    # 422 로 떨구지 않고 안전값으로 coerce. json_object 응답이라 API 레벨 enum
    # 강제가 없어 발생. 알 수 없는 값은 가장 보수적인 fallback 으로.
    @field_validator("category", mode="before")
    @classmethod
    def _coerce_category(cls, v: object) -> object:
        return v if v in _CATEGORY_VALUES else "other"

    @field_validator("direction", mode="before")
    @classmethod
    def _coerce_direction(cls, v: object) -> object:
        return v if v in _DIRECTION_VALUES else "neutral"

    @field_validator("risk_level", mode="before")
    @classmethod
    def _coerce_risk(cls, v: object) -> object:
        return v if v in _RISK_VALUES else "medium"


class DiffResult(BaseModel):
    diff_summary: str
    changes: list[DiffChange] = Field(default_factory=list)


class UserImpactedDiffResult(DiffResult):
    """DiffResult 에 *개별 사용자 영향* user_impact 자유문 + 사전 semantic
    counts 를 덧붙인 확장 모델.

    `summarize_version_diff_for_user` 가 반환. UI 는 user_impact 를 별도 카드로
    노출하면 됨 ("나에게는 어떤 영향이 있을까?").
    """
    user_impact: str = ""
    semantic_counts: dict[str, int] = Field(default_factory=dict)


class DiffSchemaError(ValueError):
    """LLM 응답이 DiffResult 스키마를 만족하지 못함."""


# ============ Embedding 기반 의미적 diff ============
#
# 텍스트 diff (Levenshtein/difflib) 가 "수정되었다" 만 알려주는 한계 (기획안 3-3
# "표현만 바뀐 무실질 수정 vs 실질 권리 변경 구분") 를 해소하기 위한 유틸.
#
# 알고리즘:
#   1. old/new 조항을 임베딩 (Upstage solar-embedding-passage).
#   2. 각 new 조항에 대해 가장 가까운 old 조항 매칭 (1:1 greedy by cosine).
#   3. cosine sim 으로 분류:
#      - sim >= NEAR_DUP_THRESHOLD (0.92): 표현만 변경 (실질 동일)
#      - SUBSTANTIVE_THRESHOLD (0.70) <= sim < 0.92: 실질 변경
#      - sim < SUBSTANTIVE_THRESHOLD: 신규 (매칭 없음)
#   4. 매칭되지 않은 old 조항은 삭제.
#
# threshold 는 환경변수로 조정 가능. 정확도 측정 후 튜닝.


SemanticChangeKind = Literal["phrasing_only", "substantive", "added", "removed"]

NEAR_DUP_THRESHOLD = float(os.getenv("DIFF_NEAR_DUP_THRESHOLD", "0.92"))
SUBSTANTIVE_THRESHOLD = float(os.getenv("DIFF_SUBSTANTIVE_THRESHOLD", "0.70"))


class SemanticChange(BaseModel):
    kind: SemanticChangeKind
    similarity: float = Field(ge=-1.0, le=1.0)
    old_index: int | None = None
    new_index: int | None = None
    old_text: str = ""
    new_text: str = ""


class SemanticDiffResult(BaseModel):
    """조항 단위 cosine 기반 분류 결과.

    counts: kind 별 개수 합산 — UI 가 "표현만 N건 / 실질 M건 / 신규 K건 / 삭제 L건"
    한 줄로 노출 가능. changes 는 raw 분류.
    """
    counts: dict[str, int] = Field(default_factory=dict)
    changes: list[SemanticChange] = Field(default_factory=list)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _classify_kind(similarity: float) -> SemanticChangeKind:
    if similarity >= NEAR_DUP_THRESHOLD:
        return "phrasing_only"
    if similarity >= SUBSTANTIVE_THRESHOLD:
        return "substantive"
    return "added"  # new 조항 기준, 매칭 못 찾으면 added


async def compute_semantic_diff(
    client: UpstageClient,
    *,
    old_clauses: list[str],
    new_clauses: list[str],
) -> SemanticDiffResult:
    """조항 단위 cosine 기반 의미적 diff. LLM 호출 없이 embedding 만 사용.

    old/new clause list 는 호출자가 미리 segmenting. 통상 사용처:
      - parsed_elements 의 text 를 그대로
      - 또는 raw_text 를 \\n\\n 으로 split

    빈 입력은 모두 added/removed 로 분류해서 반환.
    """
    out_changes: list[SemanticChange] = []
    counts: dict[str, int] = {
        "phrasing_only": 0, "substantive": 0, "added": 0, "removed": 0,
    }

    # 양쪽 다 비어 있으면 빈 결과
    if not old_clauses and not new_clauses:
        return SemanticDiffResult(counts=counts, changes=out_changes)

    # 한 쪽만 비어있으면 전부 added/removed
    if not old_clauses:
        for i, t in enumerate(new_clauses):
            out_changes.append(SemanticChange(
                kind="added", similarity=0.0, new_index=i, new_text=t,
            ))
            counts["added"] += 1
        return SemanticDiffResult(counts=counts, changes=out_changes)
    if not new_clauses:
        for i, t in enumerate(old_clauses):
            out_changes.append(SemanticChange(
                kind="removed", similarity=0.0, old_index=i, old_text=t,
            ))
            counts["removed"] += 1
        return SemanticDiffResult(counts=counts, changes=out_changes)

    # 임베딩
    old_vecs = await embed_passages(client, old_clauses)
    new_vecs = await embed_passages(client, new_clauses)

    # new 조항 각각에 대해 가장 가까운 old 조항 매칭 (greedy 1:1)
    used_old: set[int] = set()
    for new_idx, new_vec in enumerate(new_vecs):
        best_idx: int | None = None
        best_sim = -1.0
        for old_idx, old_vec in enumerate(old_vecs):
            if old_idx in used_old:
                continue
            sim = _cosine(new_vec, old_vec)
            if sim > best_sim:
                best_sim = sim
                best_idx = old_idx

        kind = _classify_kind(best_sim if best_idx is not None else 0.0)
        if kind == "added" or best_idx is None:
            out_changes.append(SemanticChange(
                kind="added", similarity=0.0,
                new_index=new_idx, new_text=new_clauses[new_idx],
            ))
            counts["added"] += 1
        else:
            used_old.add(best_idx)
            out_changes.append(SemanticChange(
                kind=kind, similarity=best_sim,
                old_index=best_idx, new_index=new_idx,
                old_text=old_clauses[best_idx], new_text=new_clauses[new_idx],
            ))
            counts[kind] += 1

    # 매칭되지 않은 old 조항 = removed
    for old_idx, old_text in enumerate(old_clauses):
        if old_idx in used_old:
            continue
        out_changes.append(SemanticChange(
            kind="removed", similarity=0.0,
            old_index=old_idx, old_text=old_text,
        ))
        counts["removed"] += 1

    return SemanticDiffResult(counts=counts, changes=out_changes)


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


def _format_user_context(user_context: dict | None) -> str:
    """user_context dict 를 prompt 에 넣을 한국어 블록으로 정렬.

    인식 키: subscribed_at, plan, billing_cycle, remaining_period_days,
    next_renewal_at, payment_method, custom_notes.
    """
    if not user_context:
        return "(컨텍스트 제공되지 않음 — 일반적 영향만 분석)"
    lines: list[str] = []
    label_map = {
        "subscribed_at": "가입일",
        "plan": "현재 플랜",
        "billing_cycle": "결제 주기",
        "remaining_period_days": "잔여 기간 (일)",
        "next_renewal_at": "다음 갱신/만료일",
        "payment_method": "결제 수단",
        "custom_notes": "추가 메모",
    }
    for key, label in label_map.items():
        val = user_context.get(key)
        if val is None or val == "":
            continue
        lines.append(f"- {label}: {val}")
    # 알려지지 않은 키는 그냥 그대로
    extras = [k for k in user_context if k not in label_map and user_context[k] is not None]
    for k in extras:
        lines.append(f"- {k}: {user_context[k]}")
    if not lines:
        return "(컨텍스트 제공되지 않음 — 일반적 영향만 분석)"
    return "\n".join(lines)


def _format_semantic_summary(semantic: "SemanticDiffResult | None") -> str:
    if semantic is None:
        return "(semantic diff 미실행 — 본문 직접 비교만 사용)"
    counts = semantic.counts or {}
    total_changes = sum(counts.values())
    if total_changes == 0:
        return "변경 없음 (모든 조항 동일)."
    parts = []
    if counts.get("phrasing_only"):
        parts.append(f"표현만 변경 {counts['phrasing_only']}건")
    if counts.get("substantive"):
        parts.append(f"실질 변경 {counts['substantive']}건")
    if counts.get("added"):
        parts.append(f"신규 조항 {counts['added']}건")
    if counts.get("removed"):
        parts.append(f"삭제 조항 {counts['removed']}건")
    return ", ".join(parts) + " (embedding cosine 기반 사전 분류)"


async def summarize_version_diff_for_user(
    client: UpstageClient,
    *,
    old_text: str,
    new_text: str,
    service_name: str,
    user_context: dict | None = None,
    semantic: "SemanticDiffResult | None" = None,
) -> UserImpactedDiffResult:
    """약관 변경의 *개별 사용자 영향* 까지 분석. 기획안 3-3 핵심.

    `summarize_version_diff` 와 같은 LLM 호출 1회. 차이:
      - user_context (가입일, plan, 잔여 기간 등) 를 prompt 에 주입.
      - 사전 계산된 `SemanticDiffResult` 가 있으면 한 줄 압축해 prior 정보로 주입.
      - 응답에 `user_impact: str` 자유문 추가.

    user_context 가 None 이면 일반 diff 와 동일하게 작동 (user_impact 는 "컨텍스트
    없음" 으로 채워짐). 호출자 책임 영역.
    """
    user_context_block = _format_user_context(user_context)
    semantic_summary_block = _format_semantic_summary(semantic)

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": USER_IMPACT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_IMPACT_USER_PROMPT_TEMPLATE.format(
                    service_name=service_name or "",
                    user_context_block=user_context_block,
                    semantic_summary_block=semantic_summary_block,
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
    # semantic counts 는 LLM 이 채우지 못하므로 호출자에서 주입.
    if semantic is not None:
        data.setdefault("semantic_counts", dict(semantic.counts))
    try:
        return UserImpactedDiffResult.model_validate(data)
    except ValidationError as e:
        raise DiffSchemaError(
            f"UserImpactedDiff response validation failed: {e}"
        ) from e
