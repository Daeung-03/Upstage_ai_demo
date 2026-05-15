"""AI/LLM 도메인 추출 스키마.

대상: Generative AI 서비스 (ChatGPT/Claude/Gemini/DeepSeek/Upstage 등) 약관.
OTT subscription, finance transaction, insurance coverage 와 모두 다른 차원
— 학습 데이터 활용, output IP 귀속, prompt 보존, API key 관리, 영문
boilerplate (binding arbitration, class action waiver 등) 가 핵심.

진단 (2026-05-16): R9 (AI_SPECIALIZED=0) vs R11 (영문 specialized) 의 trimmed mean
차이 Δ-0.6%p, noise floor 안. → prompt 차원 개선 막다른 길. AI 도메인의 진짜
병목은 **schema 미스매치**. AI 약관에 자주 등장하는 필드 (training_data_use,
output_ip_ownership, prompt_retention 등) 가 SubscriptionTerms 7섹션에 없어
모델이 가장 가까운 OTT 필드로 매핑 → strict 미스가 누적됨.

공통 구조 (`TermsChanges`) 는 OTT 스키마 재사용.
"""

from pydantic import BaseModel, Field

from ai.schemas.common import FieldValue
from ai.schemas.enums import (
    BillingCycle,
    CancellationMethod,
    ConsentMechanism,
    NoticeChannel,
    OutputIPOwnership,
    TrainingDataPolicy,
)
from ai.schemas.subscription import TermsChanges  # 공통 재사용


class ServiceTier(BaseModel):
    """구독 / 가격 / Tier 정보. AI 서비스는 free + paid + enterprise 다층 구조."""
    free_tier_offered: FieldValue[bool]
    free_tier_description: FieldValue[str]
    paid_tier_offered: FieldValue[bool]
    pricing_externally_delegated: FieldValue[bool]  # "Pricing Page 참조" 패턴
    base_price_description: FieldValue[str]         # 본문에 명시되면 자유 텍스트로
    billing_cycle: FieldValue[BillingCycle]
    auto_renewal_enabled: FieldValue[bool]


class TrainingDataUse(BaseModel):
    """사용자 input/output 의 학습 활용. AI 도메인 가장 핵심 unfair 후보."""
    input_used_for_training: FieldValue[TrainingDataPolicy]
    output_used_for_training: FieldValue[TrainingDataPolicy]
    training_use_description: FieldValue[str]
    opt_out_available: FieldValue[bool]
    opt_out_mechanism_description: FieldValue[str]


class OutputAndIP(BaseModel):
    """생성 결과 (output) 의 IP, 사용 권한, 사용자 책임."""
    output_ip_ownership: FieldValue[OutputIPOwnership]
    output_use_restrictions: FieldValue[list[str]]    # 상업적 사용 / 재배포 등 제한
    user_verification_obligation: FieldValue[bool]    # output 검토 의무
    accuracy_disclaimer: FieldValue[bool]             # "may produce inaccurate" 면책


class UsageLimits(BaseModel):
    """rate limit / quota / API key 관리."""
    rate_limit_described: FieldValue[bool]
    rate_limit_description: FieldValue[str]
    quota_described: FieldValue[bool]
    api_key_management_described: FieldValue[bool]
    api_key_security_user_burden: FieldValue[bool]    # 키 유출 책임이 이용자


class ProhibitedUse(BaseModel):
    """금지 사용 — 영문 LLM 약관에 공통적으로 등장."""
    illegal_content_prohibited: FieldValue[bool]
    harmful_content_prohibited: FieldValue[bool]
    high_risk_use_prohibited: FieldValue[bool]        # 의료/법률/금융 자문 등
    prohibited_use_categories: FieldValue[list[str]]


class ExportAndRegional(BaseModel):
    """수출통제 / 지역 제한 (영문 AI 약관 표준)."""
    export_control_clause: FieldValue[bool]
    restricted_regions: FieldValue[list[str]]
    governing_law_foreign: FieldValue[bool]           # 한국 외 법률 적용 여부


class AICancellation(BaseModel):
    """해지 / 청약철회 / 환불."""
    cancellation_method: FieldValue[CancellationMethod]
    cancellation_description: FieldValue[str]
    korea_residents_7day_refund: FieldValue[bool]     # Claude consumer §6 패턴
    non_refundable_clause: FieldValue[bool]
    refund_policy_description: FieldValue[str]


class AIDataUsage(BaseModel):
    """일반 데이터 활용 — `TrainingDataUse` 와 별개, 마케팅·제3자 공유 등 통상 항목."""
    privacy_policy_externally_delegated: FieldValue[bool]
    collected_categories: FieldValue[list[str]]
    third_party_sharing: FieldValue[bool]
    cross_border_transfer: FieldValue[bool]
    marketing_use: FieldValue[bool]
    marketing_consent: FieldValue[ConsentMechanism]


class AILiability(BaseModel):
    """면책 / 손해배상. 영문 boilerplate (IN NO EVENT WILL... INDIRECT/CONSEQUENTIAL) 패턴."""
    indirect_damages_excluded: FieldValue[bool]
    damages_cap_present: FieldValue[bool]
    damages_cap_description: FieldValue[str]
    service_disruption_compensation: FieldValue[bool]
    compensation_description: FieldValue[str]


class AIDisputes(BaseModel):
    """분쟁. 영문 LLM 약관에 강제중재·집단소송 포기 흔함."""
    governing_law: FieldValue[str]
    jurisdiction_clause: FieldValue[str]
    arbitration_required: FieldValue[bool]
    class_action_waiver: FieldValue[bool]


class AITerms(BaseModel):
    schema_version: str = "0.1.0"
    domain: str = "ai"

    service_name: str
    service_provider: str
    document_url: str | None = None
    effective_date: str | None = None
    extraction_date: str

    service_tier: ServiceTier
    training_data_use: TrainingDataUse
    output_and_ip: OutputAndIP
    usage_limits: UsageLimits
    prohibited_use: ProhibitedUse
    export_and_regional: ExportAndRegional
    cancellation: AICancellation
    terms_changes: TermsChanges
    data_usage: AIDataUsage
    liability: AILiability
    disputes: AIDisputes

    unfair_clause_flags: list[str] = Field(default_factory=list)
    raw_document_hash: str | None = None
