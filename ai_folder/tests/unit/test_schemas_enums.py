from schemas.enums import (
    BillingCycle,
    CancellationMethod,
    ConsentMechanism,
    NoticeChannel,
    ProrationPolicy,
)


def test_billing_cycle_values():
    assert {m.value for m in BillingCycle} == {
        "monthly", "quarterly", "semi_annual", "annual", "lifetime", "other",
    }


def test_notice_channel_values():
    assert {m.value for m in NoticeChannel} == {
        "email", "app_push", "sms", "web_notice", "in_app_banner",
    }


def test_consent_mechanism_includes_deemed_agreed():
    assert ConsentMechanism.DEEMED_AGREED.value == "deemed_agreed"
    assert ConsentMechanism.OPT_IN_EXPLICIT.value == "opt_in_explicit"
    assert ConsentMechanism.OPT_OUT_AVAILABLE.value == "opt_out_available"


def test_cancellation_method_values():
    assert {m.value for m in CancellationMethod} == {
        "online", "phone", "in_person", "written",
    }


def test_proration_policy_values():
    assert {m.value for m in ProrationPolicy} == {
        "full_refund", "prorated", "no_refund",
    }
