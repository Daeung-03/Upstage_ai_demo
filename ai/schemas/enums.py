from enum import Enum


class BillingCycle(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUAL = "semi_annual"
    ANNUAL = "annual"
    LIFETIME = "lifetime"
    OTHER = "other"


class NoticeChannel(str, Enum):
    EMAIL = "email"
    APP_PUSH = "app_push"
    SMS = "sms"
    WEB_NOTICE = "web_notice"
    IN_APP_BANNER = "in_app_banner"


class ConsentMechanism(str, Enum):
    OPT_IN_EXPLICIT = "opt_in_explicit"
    OPT_OUT_AVAILABLE = "opt_out_available"
    DEEMED_AGREED = "deemed_agreed"


class CancellationMethod(str, Enum):
    ONLINE = "online"
    PHONE = "phone"
    IN_PERSON = "in_person"
    WRITTEN = "written"


class ProrationPolicy(str, Enum):
    FULL_REFUND = "full_refund"
    PRORATED = "prorated"
    NO_REFUND = "no_refund"


# === Finance 도메인 ===

class FraudResponsibilityPattern(str, Enum):
    """전자금융거래 사고 책임 분배 패턴. 한국 전자금융거래법 §9 기준."""
    # 회사가 손해 배상 (이용자 고의·중과실 외)
    COMPANY_LIABLE_DEFAULT = "company_liable_default"
    # 이용자 고의·중과실 한정 면책 (전자금융거래법 표준)
    USER_GROSS_NEGLIGENCE_ONLY = "user_gross_negligence_only"
    # 회사 무한책임
    COMPANY_UNLIMITED = "company_unlimited"
    # 회사 한도책임 (금액/배수 명시)
    COMPANY_CAPPED = "company_capped"
    # 이용자 전적 부담
    USER_FULLY_LIABLE = "user_fully_liable"


class DepositProtectionStatus(str, Enum):
    """예금자보호법 적용 여부."""
    PROTECTED = "protected"               # 예금자보호 적용
    SEPARATELY_DEPOSITED = "separately_deposited"  # 별도예치 (PG/선불수단)
    NOT_PROTECTED = "not_protected"       # 비적용 (가상자산 등)
    PARTIAL = "partial"                   # 일부 적용


# === Insurance 도메인 ===

class InsuranceClaimMethod(str, Enum):
    ONLINE = "online"
    PHONE = "phone"
    IN_PERSON = "in_person"
    WRITTEN = "written"
    AGENT = "agent"


class PremiumCycle(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUAL = "semi_annual"
    ANNUAL = "annual"
    LUMP_SUM = "lump_sum"


class RefundFormula(str, Enum):
    """해지환급금 산정 방식."""
    PROPORTIONAL = "proportional"          # 일할 환급
    SURRENDER_VALUE_TABLE = "surrender_value_table"  # 해지환급금 표 기준
    CASH_VALUE_BASED = "cash_value_based"  # 책임준비금 기반
    NO_REFUND = "no_refund"


# === AI 도메인 ===

class TrainingDataPolicy(str, Enum):
    """사용자 입력·출력의 학습 활용 정책. AI 약관 핵심 unfair 후보."""
    USED_DEFAULT = "used_default"             # 옵트인 없이 기본 사용
    OPT_OUT_AVAILABLE = "opt_out_available"   # 설정으로 거부 가능
    NOT_USED = "not_used"                     # 학습 미사용 명시
    EXPLICIT_CONSENT_REQUIRED = "explicit_consent_required"  # 별도 동의 필요


class OutputIPOwnership(str, Enum):
    """생성 결과 (output) 의 저작권/IP 귀속."""
    USER = "user"               # 이용자 (대부분 영문 LLM 약관 표준)
    COMPANY = "company"
    SHARED = "shared"
    PUBLIC_DOMAIN = "public_domain"
    AMBIGUOUS = "ambiguous"
