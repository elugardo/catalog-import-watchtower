"""The five fixed alert reasons (`_docs/operations.md` -> *Alerting*, layer 1). No database."""

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.services import alerts
from app.services.importer import InjectedTransientFailure, _classify


def test_the_five_reason_strings_exactly():
    assert alerts.validation_reason(1, 1) == "VALIDATION_ERROR on attempt 1: 1 validation error"
    assert alerts.validation_reason(1, 25) == "VALIDATION_ERROR on attempt 1: 25 validation errors"
    assert alerts.validation_reason(2, 0) == "VALIDATION_ERROR on attempt 2: 0 validation errors"
    assert (
        alerts.injected_reason(1) == "TRANSIENT_STORAGE_TIMEOUT on attempt 1 (synthetic demo fault)"
    )
    assert (
        alerts.operational_reason(2)
        == "TRANSIENT_STORAGE_TIMEOUT on attempt 2 (database OperationalError)"
    )
    assert alerts.internal_reason(1) == "INTERNAL_ERROR on attempt 1 (unexpected error)"
    assert alerts.SWEEP_REASON == "INTERNAL_ERROR (found PROCESSING at startup)"


def test_reasons_are_capped_at_200_characters():
    assert len(alerts.validation_reason(10**250, 10**250)) == alerts.MAX_REASON_LENGTH == 200


class CanaryError(RuntimeError):
    pass


@pytest.mark.parametrize(
    ("exc", "code", "reason"),
    [
        (InjectedTransientFailure(), "TRANSIENT_STORAGE_TIMEOUT", alerts.injected_reason(1)),
        (
            OperationalError("SELECT CANARYSQL7", {"p": "CANARYPARAM7"}, Exception("CANARYMSG7")),
            "TRANSIENT_STORAGE_TIMEOUT",
            alerts.operational_reason(1),
        ),
        (
            IntegrityError("INSERT CANARYSQL7", {}, Exception("CANARYMSG7")),
            "INTERNAL_ERROR",
            alerts.internal_reason(1),
        ),
        (CanaryError("CANARYMSG7 CANARYSKU7"), "INTERNAL_ERROR", alerts.internal_reason(1)),
    ],
)
def test_exception_class_picks_the_code_and_its_message_is_never_used(exc, code, reason):
    assert _classify(exc, 1) == (code, reason)
    assert "CANARY" not in reason
