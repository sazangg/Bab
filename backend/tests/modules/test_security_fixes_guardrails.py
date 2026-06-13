"""Regression tests for the guardrail ReDoS-hardening fixes."""

import pytest
from pydantic import ValidationError

from app.modules.guardrails.facade import GUARDRAIL_SCAN_CHAR_LIMIT, _matched_regex_values
from app.modules.guardrails.schemas import (
    MAX_REGEX_PATTERN_LENGTH,
    MAX_REGEX_VALUES_PER_RULE,
    GuardrailRuleInput,
)


def test_rule_rejects_overlong_regex_pattern() -> None:
    with pytest.raises(ValidationError):
        GuardrailRuleInput(
            rule_type="prompt_regex",
            effect="deny",
            values=["a" * (MAX_REGEX_PATTERN_LENGTH + 1)],
        )


def test_rule_rejects_too_many_regex_values() -> None:
    with pytest.raises(ValidationError):
        GuardrailRuleInput(
            rule_type="prompt_regex",
            effect="deny",
            values=[f"pat{i}" for i in range(MAX_REGEX_VALUES_PER_RULE + 1)],
        )


@pytest.mark.asyncio
async def test_regex_match_is_bounded_to_scan_limit() -> None:
    # A match beyond the scan cap is not found (input is truncated before matching),
    # which bounds the work a single evaluation can do.
    text = "x" * (GUARDRAIL_SCAN_CHAR_LIMIT + 100) + "SECRET"
    assert await _matched_regex_values(values=["SECRET"], prompt_text=text) == []
    # The same pattern within the cap matches normally.
    assert await _matched_regex_values(values=["SECRET"], prompt_text="hello SECRET") == ["SECRET"]
