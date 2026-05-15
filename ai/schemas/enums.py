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
