from app.modules.guardrails.validation import validate_guardrail_rule_payload
from app.modules.policies.errors import PolicyValidationError
from app.modules.policies.schemas import PolicySimulationDraft
from app.modules.policies.validation import (
    validate_access_policy_public_model_payload,
    validate_limit_rule_payload,
)


def validate_policy_simulation_drafts(drafts: list[PolicySimulationDraft]) -> None:
    for draft in drafts:
        if draft.kind == "access":
            if draft.access_policy is None:
                raise PolicyValidationError
            validate_access_policy_public_model_payload(draft.access_policy.public_models)
        elif draft.kind == "limit":
            if draft.limit_policy is None:
                raise PolicyValidationError
            for rule in draft.limit_policy.rules:
                validate_limit_rule_payload(rule)
        elif draft.kind == "guardrail":
            if draft.guardrail_policy is None:
                raise PolicyValidationError
            try:
                validate_guardrail_rule_payload(draft.guardrail_policy.rules)
            except ValueError as exc:
                raise PolicyValidationError from exc
        else:
            raise PolicyValidationError
