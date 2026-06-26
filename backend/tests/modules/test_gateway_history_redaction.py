from app.modules.gateway_history.redaction import REDACTED_VALUE, redact_trace_value


def test_trace_redaction_removes_matched_content_and_preserves_metrics() -> None:
    value = {
        "matched_values": ["raw secret"],
        "matched_text": "raw prompt match",
        "prompt": "raw prompt",
        "response_text": "raw response",
        "prompt_tokens": 10,
        "completion_tokens": 20,
        "total_tokens": 30,
        "cost_cents": 3,
        "cost_micro_cents": 300_000,
    }

    redacted = redact_trace_value(value)

    assert redacted["matched_values"] == REDACTED_VALUE
    assert redacted["matched_text"] == REDACTED_VALUE
    assert redacted["prompt"] == REDACTED_VALUE
    assert redacted["response_text"] == REDACTED_VALUE
    assert redacted["prompt_tokens"] == 10
    assert redacted["completion_tokens"] == 20
    assert redacted["total_tokens"] == 30
    assert redacted["cost_cents"] == 3
    assert redacted["cost_micro_cents"] == 300_000
