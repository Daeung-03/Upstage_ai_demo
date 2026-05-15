"""파이프라인 출력을 골든 라벨과 비교해 per-field 정확도 측정.

사용:
    .venv/bin/python scripts/score_against_golden.py [pipeline_result.json] [golden.json]

기본:
    pipeline = /tmp/variance_run_1.json (가장 최근 eval run)
    golden   = data/fixtures/netflix_golden.json

출력:
- per-field 비교표 (정답/오답/null누락/오버추출)
- 섹션별 정확도
- 타입별 정확도 (enum / bool / int / str / list)
- 전체 정확도 요약
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RESULT = Path("/tmp/variance_run_1.json")
DEFAULT_GOLDEN = ROOT / "data" / "fixtures" / "netflix_golden.json"

SECTIONS = (
    "pricing", "free_trial", "cancellation", "terms_changes",
    "data_usage", "liability", "disputes",
)


def _enum_value(v):
    if hasattr(v, "value"):
        return v.value
    return v


def _normalize(v):
    """비교용 정규화: enum→canonical alias, list→normalized sorted tuple, str→strip."""
    v = _enum_value(v)
    if isinstance(v, list):
        return tuple(sorted(_normalize_list_element(x) for x in v))
    if isinstance(v, str):
        # enum alias 우선 처리 — canonical 형태로 매칭되면 동의어 그룹 정답 인정
        return _enum_canonical(v.strip())
    return v


def _is_null(v):
    if v is None:
        return True
    if isinstance(v, (list, str)) and len(v) == 0:
        return True
    return False


SEMANTIC_STR_THRESHOLD = 0.4  # SequenceMatcher ratio 0.4 이상이면 의미상 매칭으로 간주
SEMANTIC_TOKEN_JACCARD = 0.5  # 토큰 set Jaccard 0.5도 통과 (어순/조사 차이 무시)
# 0.5 → 0.4 (2026-05-15): "대한민국 서울의 관할법원" vs "서울, 대한민국" 같이 의미는 같은데
# 어순/조사 차이로 ratio 0.4 정도 나오는 케이스 회수. false positive 추적 위해 wrong 케이스도 보고.


# Enum value alias — schema에 정의된 enum 이름의 동의어 매핑.
# 같은 set에 속한 값들은 비교 시 동일하게 취급.
_ENUM_ALIAS_GROUPS = [
    {"silent_acceptance", "deemed_agreed"},      # 침묵-간주 동의 (둘 다 의사표시 의제)
    {"prorated", "prorated_refund"},             # 일할 환불 (스키마 정합 차이)
    {"opt_out_available", "opt_out"},            # 옵트아웃 (축약형)
    {"opt_in_explicit", "opt_in_required"},      # 옵트인 (스키마 정합 차이)
    # str governing_law/jurisdiction은 list_vocab이 아닌 별도 alias 그룹으로 처리
    {"California law", "California, USA", "미국 캘리포니아주 법률", "캘리포니아 주법"},
    {"Delaware law", "Delaware, USA", "미국 델라웨어주 법률"},
    {"Sweden law", "Swedish law", "스웨덴 법률"},
    {"대한민국 법률", "대한민국 법", "한국 법률", "Korean law", "Republic of Korea law"},
    {"민사소송법상 관할법원", "민사소송법 관할법원", "민사소송법에 따른 관할법원"},
]


def _enum_canonical(v):
    """enum value를 대표값으로 정규화. 동의어 그룹 첫 원소를 canonical로 사용."""
    if not isinstance(v, str):
        return v
    s = v.strip()
    for group in _ENUM_ALIAS_GROUPS:
        if s in group:
            return sorted(group)[0]  # 알파벳순 첫 원소
    return s


# 한국어/영어 list element 매핑 — 같은 set에 속한 라벨은 비교 시 동일하게 취급.
_LIST_VOCAB_GROUPS = [
    # 제3자 수신자
    {"law_enforcement", "수사기관", "정부기관", "관계기관", "수사기관 (수사목적)"},
    {"sellers", "판매자", "판매업체", "위탁사", "위탁업체"},
    {"shipping_carriers", "배송업체", "배송사", "배송 회사"},
    {"affiliates", "계열사", "관계사"},
    {"payment_processors", "결제대행사", "쿠팡페이", "payment processor", "payment processors", "billing provider"},
    # AI 도메인 vocab
    {"service_providers", "service providers", "위탁사", "service provider", "third-party service providers"},
    {"hosting_providers", "hosting providers", "클라우드 호스팅", "infrastructure providers"},
    {"model_training", "model training", "AI 학습", "학습 데이터 활용", "training data use", "improving our models"},
    {"regulators", "regulators", "정부기관", "law enforcement", "governmental authorities"},
    {"user_data_aggregators", "analytics providers", "분석 제공자", "data analytics partners"},
    # 목적
    {"transaction_fulfillment", "거래/배송", "거래 및 배송", "거래 이행", "billing settlement", "결제 정산"},
    {"fraud_prevention", "부정행위 확인", "부정행위 방지", "본인확인", "abuse prevention", "security"},
    {"marketing", "마케팅", "광고", "프로모션", "promotional", "advertising"},
    {"service_delivery", "서비스 제공", "서비스 위탁", "operate the service", "provide services"},
    {"model_improvement", "model improvement", "improving services", "research and development", "모델 개선", "서비스 개선"},
    {"legal_compliance", "legal compliance", "법령 준수", "법적 의무"},
    # 채널
    {"email", "이메일", "전자우편"},
    {"sms", "문자메시지", "문자"},
    {"in_app_banner", "인앱배너", "앱 내 공지", "사이버몰 화면", "웹사이트 공지"},
    {"app_push", "앱푸시", "앱푸쉬", "앱 알림"},
    {"web_notice", "웹공지", "공지사항", "공지사항 화면"},
    {"phone", "전화", "유선"},
    {"fax", "팩스", "모사전송"},
    # 데이터 카테고리 (자주 나오는 것)
    {"device_info", "device_usage", "기기정보", "단말기 정보"},
    {"behavioral", "behavioral_data", "이용기록", "사용기록"},
]


def _normalize_list_element(s) -> str:
    """list element 정규화: vocab group 매핑 + 괄호 부연 제거 + 공백/특수문자 정리."""
    import re
    if s is None:
        return ""
    s = str(s).strip()
    # 괄호 내 부연 제거: "수사기관 (수사목적)" → "수사기관"
    s_stripped = re.sub(r"\s*\([^)]*\)", "", s).strip()
    # vocab group lookup
    for group in _LIST_VOCAB_GROUPS:
        if s_stripped in group or s in group:
            return sorted(group)[0]
    # underscore / 공백 통일
    return re.sub(r"\s+", " ", s_stripped.replace("_", " ")).strip().lower()


# Unfair clause flag alias — POST-XX 코드 ↔ 한글 표준명 ↔ 영문 라벨 매핑.
# 같은 그룹에 속한 flag는 비교 시 동일 취급. canonical은 정렬 첫 원소.
_FLAG_ALIAS_GROUPS = [
    {"POST-01", "약관 일방 변경권", "unilateral_change", "약관 일방 변경",
     "일방적 약관 변경", "회사의 일방적 변경권"},
    {"POST-02", "다크패턴 — 해지 절차 복잡화", "complex_cancellation",
     "해지 절차 복잡화", "다크패턴 해지", "해지 어려움"},
    {"POST-03", "환불 거부", "refund_denial", "환불 불가",
     "환불 거부 (시청 시 청약철회 권리 소멸)", "no_refund"},
    {"POST-04", "면책/손배 제한", "liability_cap", "면책_손배_제한",
     "손해배상 한도", "책임 제한"},
    {"POST-05", "분쟁/집단소송 포기", "arbitration_class_waiver",
     "의사표시_의제", "의사표시 의제", "강제 중재", "집단소송 포기",
     "준거법 외국법", "분쟁 해결 포기"},
    # AI 학습 데이터 — POST 카테고리에 없는 LLM-specific flag
    {"AI 학습 데이터 활용", "AI 학습 데이터 활용 (옵트아웃)", "ai_training_data",
     "model training opt-in", "학습 데이터 사용"},
]


def _flag_canonical(s: str) -> str:
    """flag 정규화: 괄호/언더스코어 제거 + alias 그룹 canonical 매핑."""
    import re
    if not s:
        return ""
    # 1차: 괄호 내 부연 / underscore / 공백 정리
    base = re.sub(r"\s*\([^)]*\)", "", s).strip()
    base = base.replace("_", " ")
    base = re.sub(r"\s+", " ", base).strip()
    # 2차: alias 그룹 lookup (원본 + 정규화된 형태 둘 다 시도)
    for group in _FLAG_ALIAS_GROUPS:
        if s in group or base in group:
            return sorted(group)[0]
    return base


def _normalize_flag(s: str) -> str:
    """unfair_clause_flag 정규화 (backward-compatible 이름). canonical alias 매핑 사용."""
    return _flag_canonical(s)


def _str_similar(a: str, b: str) -> float:
    """두 문자열의 유사도 (0-1). difflib SequenceMatcher 사용."""
    from difflib import SequenceMatcher
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.strip(), b.strip()).ratio()


# 의미 임베딩 매칭용 — lazy load. 라이브러리 없으면 fallback (휴리스틱만 사용).
_EMBEDDING_MODEL = None
_EMBEDDING_CACHE: dict[str, "object"] = {}
_EMBEDDING_LOAD_FAILED = False
SEMANTIC_EMBEDDING_THRESHOLD = 0.7  # cosine 유사도 임계 — 한국어 paraphrase에 robust한 값


def _embedding_model():
    """sentence-transformers 모델 lazy 로드. 라이브러리 미설치/로드 실패 시 None."""
    global _EMBEDDING_MODEL, _EMBEDDING_LOAD_FAILED
    if _EMBEDDING_LOAD_FAILED:
        return None
    if _EMBEDDING_MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
            _EMBEDDING_MODEL = SentenceTransformer(
                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
            )
        except (ImportError, Exception) as e:  # noqa: BLE001
            print(f"[warning] embedding 모델 로드 실패 — 휴리스틱만 사용: {type(e).__name__}: {str(e)[:80]}")
            _EMBEDDING_LOAD_FAILED = True
            return None
    return _EMBEDDING_MODEL


def _embed(s: str):
    """문자열을 임베딩 벡터로 변환. 캐시 활용. 모델 로드 실패 시 None."""
    if not s:
        return None
    s = s.strip()
    if s in _EMBEDDING_CACHE:
        return _EMBEDDING_CACHE[s]
    model = _embedding_model()
    if model is None:
        return None
    vec = model.encode(s, convert_to_numpy=True, normalize_embeddings=True)
    _EMBEDDING_CACHE[s] = vec
    return vec


def _str_embedding_similar(a: str, b: str) -> float:
    """두 문자열 의미 유사도 — multilingual MiniLM cosine. 모델 없으면 0.0."""
    va, vb = _embed(a), _embed(b)
    if va is None or vb is None:
        return 0.0
    # normalized 임베딩이라 dot product = cosine similarity
    return float((va * vb).sum())


def _token_jaccard(a: str, b: str) -> float:
    """토큰 set Jaccard 유사도. 어순/조사 차이를 무시하는 보조 매칭.

    예: "민사소송법상 관할법원" vs "민사소송법 관할법원" → Jaccard 0.67 통과
        "결제금액의 10% (이용)" vs "결제금액의 10%" → Jaccard 0.5+ 통과
    """
    import re
    if not a or not b:
        return 0.0
    # 토큰화: 공백/조사/구두점 제거. 2자 이상만 유효 토큰.
    def toks(s):
        s = re.sub(r"[(),.·;\"'`「」『』\[\]【】]+", " ", s)
        return {t for t in s.split() if len(t) >= 2}
    sa, sb = toks(a), toks(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _list_str_similar(a, b) -> bool:
    """두 list가 의미상 같은지 — vocab normalization 후 set 비교 + 원소별 fuzzy 매칭.

    1) 양쪽을 vocab group canonical로 normalize 후 set 비교 (한국어/영어 매핑 흡수)
    2) normalize 후에도 다르면 원소별 fuzzy 매칭 fallback
    """
    if not isinstance(a, list) or not isinstance(b, list):
        return False
    if len(a) == 0 and len(b) == 0:
        return True

    # 1차: vocab normalization 후 set 비교
    na = {_normalize_list_element(x) for x in a}
    nb = {_normalize_list_element(x) for x in b}
    if na and nb:
        overlap = len(na & nb)
        # 60% 이상 겹치면 통과 (a 또는 b 중 작은 쪽 기준)
        if overlap >= max(1, min(len(na), len(nb)) * 0.6):
            return True

    # 2차: 길이 차이가 너무 크면 fail
    if abs(len(a) - len(b)) > max(2, len(a) // 2):
        return False
    # 원소별 fuzzy 매칭 (정규화된 형태 + 원본 둘 다 시도)
    matches = 0
    for x in a:
        nx = _normalize_list_element(x)
        if any(
            _normalize_list_element(y) == nx
            or _str_similar(str(x), str(y)) >= 0.6
            or _str_similar(nx, _normalize_list_element(y)) >= 0.6
            for y in b
        ):
            matches += 1
    return matches >= len(a) * 0.6


def classify(expected, actual, *, semantic: bool = False) -> str:
    """expected vs actual 매칭 결과 분류. semantic=True면 str/list 유사도 매칭."""
    # 사용자 라벨이 "AMBIGUOUS" 문자열인 경우는 bool 비교 불가 → ok_null 취급
    if isinstance(expected, str) and expected.upper() == "AMBIGUOUS":
        return "ok_null"
    e_null, a_null = _is_null(expected), _is_null(actual)
    if e_null and a_null:
        return "ok_null"
    if e_null and not a_null:
        return "over_extracted"
    if not e_null and a_null:
        return "missed"
    if _normalize(expected) == _normalize(actual):
        return "ok"
    # semantic mode: str/list 유사도 매칭
    if semantic:
        if isinstance(expected, str) and isinstance(actual, str):
            # SequenceMatcher / 토큰 Jaccard / substring 중 하나라도 임계값 넘으면 통과
            if (
                _str_similar(expected, actual) >= SEMANTIC_STR_THRESHOLD
                or _token_jaccard(expected, actual) >= SEMANTIC_TOKEN_JACCARD
            ):
                return "ok"
            # substring 포함도 통과: "결제금액의 10%"가 "결제금액의 10% (이용)" 안에 있으면 OK
            ea, aa = expected.strip(), actual.strip()
            if len(ea) >= 5 and len(aa) >= 5 and (ea in aa or aa in ea):
                return "ok"
            # 임베딩 의미 매칭 — 휴리스틱이 모두 실패해도 의미상 가까우면 ok
            if _str_embedding_similar(expected, actual) >= SEMANTIC_EMBEDDING_THRESHOLD:
                return "ok"
        if isinstance(expected, list) and isinstance(actual, list):
            if _list_str_similar(expected, actual):
                return "ok"
    return "wrong"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    semantic = "--semantic" in flags
    result_path = Path(args[0]) if len(args) > 0 else DEFAULT_RESULT
    golden_path = Path(args[1]) if len(args) > 1 else DEFAULT_GOLDEN
    if semantic:
        print(f"[semantic mode: str/list fuzzy matching, threshold={SEMANTIC_STR_THRESHOLD}]")
    if not result_path.exists():
        print(f"ERROR: pipeline result {result_path} not found")
        sys.exit(1)
    if not golden_path.exists():
        print(f"ERROR: golden file {golden_path} not found")
        sys.exit(1)

    with open(result_path) as f:
        run = json.load(f)
    with open(golden_path) as f:
        golden = json.load(f)

    # Type hints for each field — for type-level metrics
    type_hints = {
        "int": [
            "pricing.base_price_krw", "pricing.price_change_notice_days",
            "free_trial.duration_days", "free_trial.notice_before_conversion_days",
            "cancellation.notice_period_days",
            "terms_changes.notice_lead_time_days",
            "data_usage.retention_period_months",
        ],
        "bool": [
            "pricing.auto_renewal_enabled",
            "free_trial.offered", "free_trial.auto_convert_to_paid",
            "free_trial.cancel_required_before_end", "free_trial.payment_method_required_upfront",
            "cancellation.penalty_present",
            "terms_changes.user_right_to_terminate_on_change", "terms_changes.silent_acceptance_clause",
            "data_usage.third_party_sharing", "data_usage.marketing_use", "data_usage.cross_border_transfer",
            "liability.service_disruption_compensation", "liability.damages_cap_present",
            "liability.indirect_damages_excluded",
            "disputes.arbitration_required", "disputes.class_action_waiver",
        ],
        "enum": [
            "pricing.billing_cycle", "pricing.auto_renewal_consent",
            "cancellation.method", "cancellation.proration_policy",
            "terms_changes.user_consent_mechanism",
            "data_usage.marketing_consent",
        ],
        "list": [
            "pricing.price_change_notice_channels",
            "cancellation.blackout_periods",
            "terms_changes.notice_channels",
            "data_usage.collected_categories", "data_usage.third_party_recipients", "data_usage.third_party_purposes",
        ],
        "str": [
            "cancellation.method_description", "cancellation.penalty_description",
            "liability.compensation_description", "liability.damages_cap_description", "liability.force_majeure_scope",
            "disputes.governing_law", "disputes.jurisdiction_clause",
        ],
    }
    field_to_type = {}
    for t, fields in type_hints.items():
        for f in fields:
            field_to_type[f] = t

    # Per-field comparison
    print("=" * 110)
    print("PER-FIELD ACCURACY (expected vs actual)")
    print("=" * 110)
    print(f"{'Field':<55} {'Type':<6} {'Expected':<22} {'Actual':<22} {'Result'}")
    print("-" * 110)

    counters: dict[str, int] = {"ok": 0, "ok_null": 0, "wrong": 0, "missed": 0, "over_extracted": 0}
    type_counters: dict[str, dict[str, int]] = {}
    section_counters: dict[str, dict[str, int]] = {}

    for section in SECTIONS:
        for field, fv in run["terms"][section].items():
            key = f"{section}.{field}"
            actual = _enum_value(fv["value"])
            golden_entry = golden.get(key)
            if golden_entry is None:
                continue  # 정답 없음
            expected = golden_entry.get("expected")
            cls = classify(expected, actual, semantic=semantic)
            counters[cls] += 1
            t = field_to_type.get(key, "?")
            type_counters.setdefault(t, dict.fromkeys(counters, 0))[cls] += 1
            section_counters.setdefault(section, dict.fromkeys(counters, 0))[cls] += 1

            mark = {"ok": "✓", "ok_null": "·", "wrong": "✗", "missed": "—", "over_extracted": "+"}[cls]
            print(f"{key:<55} {t:<6} {str(expected)[:21]:<22} {str(actual)[:21]:<22} {mark} {cls}")

    print()
    total = sum(counters.values())
    correct = counters["ok"] + counters["ok_null"]
    print("=" * 110)
    print(f"OVERALL ({total} fields)")
    print(f"  ✓ ok (correct non-null):    {counters['ok']:>3} ({100 * counters['ok'] // total}%)")
    print(f"  · ok_null (correct null):   {counters['ok_null']:>3} ({100 * counters['ok_null'] // total}%)")
    print(f"  — missed (had answer, model said null): {counters['missed']:>3} ({100 * counters['missed'] // total}%)")
    print(f"  ✗ wrong (different value): {counters['wrong']:>3} ({100 * counters['wrong'] // total}%)")
    print(f"  + over_extracted (no answer, model invented): {counters['over_extracted']:>3} ({100 * counters['over_extracted'] // total}%)")
    print(f"  --- accuracy = (ok + ok_null) / total = {100 * correct // total}% ---")
    print()

    print("BY TYPE")
    for t, c in type_counters.items():
        tot = sum(c.values())
        acc = (c["ok"] + c["ok_null"]) / max(tot, 1) * 100
        print(f"  {t:<6}  n={tot:>2}  acc={acc:>5.1f}%   ok={c['ok']} ok_null={c['ok_null']} wrong={c['wrong']} missed={c['missed']} over={c['over_extracted']}")
    print()
    print("BY SECTION")
    for s, c in section_counters.items():
        tot = sum(c.values())
        acc = (c["ok"] + c["ok_null"]) / max(tot, 1) * 100
        print(f"  {s:<14}  n={tot:>2}  acc={acc:>5.1f}%")
    print()

    # unfair_clause_flags
    gold_flags_raw = golden.get("unfair_clause_flags", {}).get("expected") or []
    gold_flags = set(gold_flags_raw)
    # 정규화된 비교용 set (괄호 부연/언더스코어/공백 제거)
    gold_flags_norm = {_normalize_flag(f) for f in gold_flags_raw}
    actual_flags = set(run["terms"].get("unfair_clause_flags") or [])
    print("unfair_clause_flags:")
    print(f"  expected: {sorted(gold_flags)}")
    actual_flags_norm = {_normalize_flag(f) for f in (run["terms"].get("unfair_clause_flags") or [])}
    matched_norm = actual_flags_norm & gold_flags_norm
    prec_norm = len(matched_norm) / max(len(actual_flags_norm), 1)
    rec_norm = len(matched_norm) / max(len(gold_flags_norm), 1)
    print(f"  actual:   {sorted(actual_flags)}")
    print(f"  precision={len(actual_flags & gold_flags)/max(len(actual_flags),1):.2f}  recall={len(actual_flags & gold_flags)/max(len(gold_flags),1):.2f} (strict)")
    print(f"  precision={prec_norm:.2f}  recall={rec_norm:.2f} (normalized: 괄호 부연 제거)")


if __name__ == "__main__":
    main()
