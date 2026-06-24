from app.modules.guardrails.schemas import GuardrailRuleInput
from app.modules.policies.dimensions import PolicyDimensionStage, validate_matcher
from app.modules.policies.errors import PolicyValidationError


def validate_guardrail_rule_payload(rules: list[GuardrailRuleInput]) -> None:
    for rule in rules:
        stage = (
            PolicyDimensionStage.RESPONSE_GUARDRAIL
            if rule.phase == "response"
            else PolicyDimensionStage.REQUEST_GUARDRAIL
        )
        for matcher in rule.matchers:
            try:
                validate_matcher(
                    dimension=matcher.dimension,
                    operator=matcher.operator,
                    value=matcher.value_json,
                    stage=stage,
                )
            except (PolicyValidationError, ValueError) as exc:
                raise ValueError("invalid guardrail matcher") from exc
