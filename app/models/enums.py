import enum

class TermDomain(str, enum.Enum):
    FINANCE = "FINANCE"
    OTT = "OTT"
    INSURANCE = "INSURANCE"
    APP = "APP"
    AI = "AI"
    MEDICAL = "MEDICAL"
    TELECOM = "TELECOM"
    ETC = "ETC"

class TermStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"

class ClauseType(str, enum.Enum):
    PAYMENT = "PAYMENT"
    CANCELLATION = "CANCELLATION"
    PRIVACY = "PRIVACY"
    RENEWAL = "RENEWAL"
    LIABILITY = "LIABILITY"
    # v1.1: 약관 변경 / 의사표시 의제 / 통지 기간 등 (이전엔 ETC 로 묶여 분류 불가).
    # migration 0004 이전 DB 에는 enum 값 없을 수 있음 — 호출자 fallback 책임.
    TERMS_CHANGE = "TERMS_CHANGE"
    ETC = "ETC"

class EventType(str, enum.Enum):
    SUBSCRIBED_AT = "SUBSCRIBED_AT"
    RENEWAL_AT = "RENEWAL_AT"
    CANCEL_DEADLINE = "CANCEL_DEADLINE"
    TRIAL_END = "TRIAL_END"
    ETC = "ETC"

class NotificationStatus(str, enum.Enum):
    UNREAD = "UNREAD"
    READ = "READ"

class MessageRole(str, enum.Enum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"