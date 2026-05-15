"""기존 OTT-shaped fintech golden 을 FinanceTerms v0.3 schema 좌표계로 재매핑.

상대 라벨링 (relabel) 이 아니라 **단순 좌표계 변환** (remap) 임:
- 호환 필드 (terms_changes, data_usage 일부, disputes governing/jurisdiction) 는
  expected 값을 그대로 옮긴다.
- OTT 전용 필드 (pricing.*, free_trial.*, liability.*) 는 drop.
- Finance 전용 신규 필드 (fees.*, transaction_limits.*, deposit_protection.*) 는
  expected=null + _remap_note 로 두어 후속 라벨링 표시.
- 일부 신규 필드는 기존 라벨에서 inferred 가능 (예: 전자금융거래법 §9 표준 패턴).

사용:
    .venv/bin/python scripts/remap_fintech_golden_v03.py
    → data/fixtures/{toss,kakaopay,banksalad}_golden_v03_finance.json 생성
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "data" / "fixtures"

# 그대로 옮기는 필드 (OTT path == Finance path)
COPY_FIELDS = (
    "terms_changes.notice_channels",
    "terms_changes.notice_lead_time_days",
    "terms_changes.user_consent_mechanism",
    "terms_changes.user_right_to_terminate_on_change",
    "terms_changes.silent_acceptance_clause",
    "data_usage.collected_categories",
    "data_usage.third_party_sharing",
    "data_usage.third_party_recipients",
    "data_usage.marketing_use",
    "data_usage.marketing_consent",
    "data_usage.cross_border_transfer",
    "disputes.governing_law",
    "disputes.jurisdiction_clause",
    "unfair_clause_flags",
)

# OTT path → Finance path 단순 rename
RENAME_FIELDS: dict[str, str] = {
    "cancellation.method": "account_termination.method",
    "cancellation.method_description": "account_termination.method_description",
}

# v0.3 추가 필드 (모두 신규 라벨 필요)
NEW_FIELDS = (
    "fees.has_transaction_fees",
    "fees.transaction_fees_description",
    "fees.fee_change_notice_days",
    "fees.fee_change_notice_channels",
    "transaction_limits.per_transaction_limit_krw",
    "transaction_limits.daily_limit_krw",
    "transaction_limits.monthly_limit_krw",
    "transaction_limits.limits_description",
    "liability_allocation.responsibility_pattern",
    "liability_allocation.user_burden_description",
    "liability_allocation.company_compensation_scope",
    "liability_allocation.user_notification_deadline_hours",
    "liability_allocation.company_response_deadline_days",
    "deposit_protection.status",
    "deposit_protection.description",
    "deposit_protection.coverage_limit_krw",
    "account_termination.dormancy_period_months",
    "account_termination.balance_handling_description",
    "data_usage.privacy_policy_externally_delegated",
    "disputes.financial_supervisor_complaint_channel",
    "disputes.complaint_channel_description",
)


def _empty_label() -> dict:
    return {
        "expected": None,
        "_remap_note": "v0.4 라벨 추가 예정 — finance 도메인 신규 필드",
    }


def _copy_label(src: dict, *, src_path: str) -> dict:
    """OTT 라벨에서 expected/source 만 들고 v0.3 라벨로."""
    return {
        "expected": src.get("expected"),
        "_remap_source": src_path,
        "_source_quote": src.get("source_quote") or "",
        "_source_page": src.get("source_page"),
        "_remap_note": "OTT v0.2 라벨 그대로 — 의미 동일",
    }


def _infer_liability_from_ott(ott: dict) -> dict[str, dict]:
    """OTT liability.compensation_description 에서 §9 패턴 추론.

    fintech 골든의 liability.compensation_description 이 "회사 귀책 외 책임 부담하지
    않음" / "회원 통지 후 제3자 부정사용 손해 배상 책임" / "회사의 고의 또는 중과실로
    인한 손해는 배상" 같이 한국 전자금융거래법 §9 표준이면 user_gross_negligence_only.
    """
    desc_field = ott.get("liability.compensation_description") or {}
    desc = (desc_field.get("expected") or "").strip()
    if not desc:
        return {}
    text = desc.lower()
    pattern: str | None = None
    if "고의" in desc and "중과실" in desc:
        pattern = "user_gross_negligence_only"
    elif "회사 귀책 외" in desc or "회사의 귀책사유 외" in desc:
        pattern = "user_gross_negligence_only"
    elif "제3자 부정사용" in desc:
        pattern = "user_gross_negligence_only"
    elif "책임지지 않" in text:
        pattern = "user_fully_liable"
    if pattern is None:
        return {}
    return {
        "liability_allocation.responsibility_pattern": {
            "expected": pattern,
            "_remap_note": (
                f"OTT liability.compensation_description='{desc}' 에서 inferred — "
                "한국 전자금융거래법 §9 표준 패턴"
            ),
            "_source_quote": desc_field.get("source_quote") or "",
            "_source_page": desc_field.get("source_page"),
        },
        "liability_allocation.company_compensation_scope": {
            "expected": desc,
            "_remap_source": "liability.compensation_description",
            "_source_quote": desc_field.get("source_quote") or "",
            "_source_page": desc_field.get("source_page"),
        },
    }


def remap_one(ott_path: Path) -> dict:
    with open(ott_path) as f:
        ott = json.load(f)

    meta_in = ott.get("_meta", {})
    meta_out = {
        "service_name": meta_in.get("service_name"),
        "service_provider": meta_in.get("service_provider"),
        "schema_version": "v0.3-finance",
        "domain": "finance",
        "labeler": "remap from v0.2 (scripts/remap_fintech_golden_v03.py)",
        "extraction_date": meta_in.get("extraction_date"),
        "source_v02_path": ott_path.name,
        "remap_changelog": [
            "v0.3 (2026-05-15): OTT-shaped v0.2 → FinanceTerms 좌표계 자동 변환. "
            "호환 필드는 expected 보존, 신규 finance-only 필드는 expected=null. "
            "liability_allocation.responsibility_pattern 은 §9 패턴 inferred."
        ],
        "note": meta_in.get("note", ""),
    }

    out: dict = {"_meta": meta_out}

    # COPY
    for path in COPY_FIELDS:
        src = ott.get(path)
        if src is None:
            continue
        if path == "unfair_clause_flags":
            out[path] = {"expected": src.get("expected") if isinstance(src, dict) else src,
                          "_remap_source": "unfair_clause_flags (unchanged)"}
        else:
            out[path] = _copy_label(src, src_path=path)

    # RENAME
    for src_path, dst_path in RENAME_FIELDS.items():
        src = ott.get(src_path)
        if src is None:
            continue
        out[dst_path] = _copy_label(src, src_path=src_path)

    # INFER (liability)
    out.update(_infer_liability_from_ott(ott))

    # NEW FIELDS — empty 라벨로
    for path in NEW_FIELDS:
        if path not in out:
            out[path] = _empty_label()

    return out


def main() -> None:
    targets = ("toss", "kakaopay", "banksalad")
    for name in targets:
        src = FIXTURE_DIR / f"{name}_golden.json"
        if not src.exists():
            print(f"!  skip — {src.name} 없음")
            continue
        out = remap_one(src)
        dst = FIXTURE_DIR / f"{name}_golden_v03_finance.json"
        with open(dst, "w") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        # 통계
        filled = sum(
            1 for k, v in out.items()
            if k != "_meta" and isinstance(v, dict) and v.get("expected") is not None
        )
        empty = sum(
            1 for k, v in out.items()
            if k != "_meta" and isinstance(v, dict) and v.get("expected") is None
        )
        print(f"✓ {dst.name}: filled={filled}, empty={empty}")


if __name__ == "__main__":
    main()
