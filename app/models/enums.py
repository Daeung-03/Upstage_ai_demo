import enum

class TermDomain(str, enum.Enum):
    FINANCE = "FINANCE"
    OTT = "OTT"
    INSURANCE = "INSURANCE"
    APP = "APP"
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