from app.modules.policies.errors import PolicyValidationError
from app.modules.policies.validation import (
    validate_access_policy_public_model_payload,
    validate_limit_rule_payload,
)
from app.modules.policy_simulation import adapters
from app.modules.policy_simulation.errors import PolicySimulationValidationError
from app.modules.policy_simulation.schemas import PolicySimulationDraft


def validate_policy_simulation_drafts(drafts: list[PolicySimulationDraft]) -> None:
    for draft in drafts:
        if draft.kind == "access":
            if draft.access_policy is None:
                raise PolicySimulationValidationError
            try:
                validate_access_policy_public_model_payload(draft.access_policy.public_models)
            except PolicyValidationError as exc:
                raise PolicySimulationValidationError from exc
        elif draft.kind == "limit":
            if draft.limit_policy is None:
                raise PolicySimulationValidationError
            try:
                for rule in draft.limit_policy.rules:
                    validate_limit_rule_payload(rule)
            except PolicyValidationError as exc:
                raise PolicySimulationValidationError from exc
        elif draft.kind == "guardrail":
            adapters.guardrail.validate_guardrail_draft_policy(draft)
        else:
            raise PolicySimulationValidationError
