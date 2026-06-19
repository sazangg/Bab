from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.modules.policies.errors import PolicyValidationError


class PolicyDimensionStage(StrEnum):
    PRE_RESOLUTION = "pre_resolution"
    ACCESS_RESOLUTION = "access_resolution"
    REQUEST_GUARDRAIL = "request_guardrail"
    LIMIT_RESERVATION = "limit_reservation"
    PROVIDER_ATTEMPT = "provider_attempt"
    RESPONSE_GUARDRAIL = "response_guardrail"
    LIMIT_COMMIT = "limit_commit"


class PolicyDimensionType(StrEnum):
    BOOLEAN = "boolean"
    ENUM = "enum"
    STRING = "string"
    UUID = "uuid"


class PolicyMatcherOperator(StrEnum):
    EQ = "eq"
    IN = "in"
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"


@dataclass(frozen=True)
class PolicyDimension:
    name: str
    value_type: PolicyDimensionType
    filterable: bool
    partitionable: bool
    stages: frozenset[PolicyDimensionStage]
    resource_kind: str | None = None
    allowed_values: frozenset[str] | None = None


ALL_MATCHER_OPERATORS = frozenset(PolicyMatcherOperator)
VALUE_MATCHER_OPERATORS = frozenset(
    {
        PolicyMatcherOperator.EQ,
        PolicyMatcherOperator.IN,
    }
)
PRESENCE_MATCHER_OPERATORS = frozenset(
    {
        PolicyMatcherOperator.EXISTS,
        PolicyMatcherOperator.NOT_EXISTS,
    }
)

PRE_RESOLUTION_DIMENSIONS = frozenset(
    {
        "gateway_endpoint",
        "requested_model",
        "streaming",
    }
)
ACCESS_RESOLUTION_DIMENSIONS = frozenset(
    {
        "org_id",
        "team_id",
        "project_id",
        "virtual_key_id",
        "gateway_endpoint",
        "requested_model",
        "streaming",
        "public_model_name",
    }
)
REQUEST_GUARDRAIL_DIMENSIONS = frozenset(
    {
        "org_id",
        "team_id",
        "project_id",
        "virtual_key_id",
        "provider_id",
        "credential_pool_id",
        "provider_model_offering_id",
        "public_model_id",
        "public_model_name",
        "route_candidate_id",
        "access_policy_id",
        "access_policy_revision_id",
        "gateway_endpoint",
        "streaming",
        "catalog_entry_id",
        "model_family",
        "input_modality",
        "output_modality",
    }
)
PROVIDER_ATTEMPT_DIMENSIONS = REQUEST_GUARDRAIL_DIMENSIONS | frozenset(
    {
        "provider_credential_id",
    }
)

STAGE_DIMENSION_NAMES: dict[PolicyDimensionStage, frozenset[str]] = {
    PolicyDimensionStage.PRE_RESOLUTION: PRE_RESOLUTION_DIMENSIONS,
    PolicyDimensionStage.ACCESS_RESOLUTION: ACCESS_RESOLUTION_DIMENSIONS,
    PolicyDimensionStage.REQUEST_GUARDRAIL: REQUEST_GUARDRAIL_DIMENSIONS,
    PolicyDimensionStage.LIMIT_RESERVATION: REQUEST_GUARDRAIL_DIMENSIONS,
    PolicyDimensionStage.PROVIDER_ATTEMPT: PROVIDER_ATTEMPT_DIMENSIONS,
    PolicyDimensionStage.RESPONSE_GUARDRAIL: PROVIDER_ATTEMPT_DIMENSIONS,
    PolicyDimensionStage.LIMIT_COMMIT: PROVIDER_ATTEMPT_DIMENSIONS,
}


def _stages_for_dimension(name: str) -> frozenset[PolicyDimensionStage]:
    return frozenset(
        stage for stage, dimensions in STAGE_DIMENSION_NAMES.items() if name in dimensions
    )


def _dimension(
    name: str,
    value_type: PolicyDimensionType,
    *,
    filterable: bool = True,
    partitionable: bool = True,
    resource_kind: str | None = None,
    allowed_values: frozenset[str] | None = None,
) -> PolicyDimension:
    return PolicyDimension(
        name=name,
        value_type=value_type,
        filterable=filterable,
        partitionable=partitionable,
        stages=_stages_for_dimension(name),
        resource_kind=resource_kind,
        allowed_values=allowed_values,
    )


DIMENSIONS: dict[str, PolicyDimension] = {
    "org_id": _dimension("org_id", PolicyDimensionType.UUID, resource_kind="organization"),
    "team_id": _dimension("team_id", PolicyDimensionType.UUID, resource_kind="team"),
    "project_id": _dimension("project_id", PolicyDimensionType.UUID, resource_kind="project"),
    "virtual_key_id": _dimension(
        "virtual_key_id", PolicyDimensionType.UUID, resource_kind="virtual_key"
    ),
    "provider_id": _dimension("provider_id", PolicyDimensionType.UUID, resource_kind="provider"),
    "credential_pool_id": _dimension(
        "credential_pool_id", PolicyDimensionType.UUID, resource_kind="credential_pool"
    ),
    "provider_credential_id": _dimension(
        "provider_credential_id", PolicyDimensionType.UUID, resource_kind="provider_credential"
    ),
    "provider_model_offering_id": _dimension(
        "provider_model_offering_id",
        PolicyDimensionType.UUID,
        resource_kind="provider_model_offering",
    ),
    "public_model_id": _dimension(
        "public_model_id", PolicyDimensionType.UUID, resource_kind="public_model"
    ),
    "public_model_name": _dimension("public_model_name", PolicyDimensionType.STRING),
    "route_candidate_id": _dimension(
        "route_candidate_id", PolicyDimensionType.UUID, resource_kind="route_candidate"
    ),
    "access_policy_id": _dimension(
        "access_policy_id", PolicyDimensionType.UUID, resource_kind="access_policy"
    ),
    "access_policy_revision_id": _dimension(
        "access_policy_revision_id", PolicyDimensionType.UUID, resource_kind="policy_revision"
    ),
    "gateway_endpoint": _dimension(
        "gateway_endpoint",
        PolicyDimensionType.ENUM,
        allowed_values=frozenset(
            {"chat_completions", "responses", "completions", "anthropic_messages"}
        ),
    ),
    "requested_model": _dimension("requested_model", PolicyDimensionType.STRING),
    "streaming": _dimension("streaming", PolicyDimensionType.BOOLEAN),
    "catalog_entry_id": _dimension(
        "catalog_entry_id", PolicyDimensionType.UUID, resource_kind="model_catalog_entry"
    ),
    "model_family": _dimension("model_family", PolicyDimensionType.STRING),
    "input_modality": _dimension("input_modality", PolicyDimensionType.STRING),
    "output_modality": _dimension("output_modality", PolicyDimensionType.STRING),
}

ATTEMPT_SCOPED_DIMENSIONS = frozenset(
    {
        "provider_id",
        "credential_pool_id",
        "provider_credential_id",
        "provider_model_offering_id",
        "route_candidate_id",
    }
)


def get_dimension(name: str) -> PolicyDimension:
    try:
        return DIMENSIONS[name]
    except KeyError as exc:
        raise PolicyValidationError(f"Unknown policy dimension: {name}") from exc


def validate_dimension_stage(
    *,
    dimension: str,
    stage: PolicyDimensionStage | str,
    enforce: bool = True,
) -> PolicyDimension:
    resolved_stage = PolicyDimensionStage(stage)
    definition = get_dimension(dimension)
    if resolved_stage in definition.stages:
        return definition
    if enforce:
        raise PolicyValidationError(
            f"Policy dimension {dimension} is not available at stage {resolved_stage.value}"
        )
    return definition


def validate_matcher(
    *,
    dimension: str,
    operator: PolicyMatcherOperator | str,
    stage: PolicyDimensionStage | str,
    value: Any = None,
    enforce: bool = True,
) -> PolicyDimension:
    definition = validate_dimension_stage(dimension=dimension, stage=stage, enforce=enforce)
    resolved_operator = PolicyMatcherOperator(operator)
    if not definition.filterable:
        raise PolicyValidationError(f"Policy dimension {dimension} is not filterable")
    if resolved_operator not in ALL_MATCHER_OPERATORS:
        raise PolicyValidationError(f"Unsupported matcher operator: {operator}")
    if resolved_operator in VALUE_MATCHER_OPERATORS and value is None:
        raise PolicyValidationError(f"Matcher operator {resolved_operator.value} requires a value")
    if resolved_operator in PRESENCE_MATCHER_OPERATORS and value is not None:
        raise PolicyValidationError(
            f"Matcher operator {resolved_operator.value} does not accept a value"
        )
    if resolved_operator == PolicyMatcherOperator.IN and not isinstance(value, list | tuple | set):
        raise PolicyValidationError("Matcher operator in requires a list of values")
    if definition.allowed_values is not None:
        values = value if isinstance(value, list | tuple | set) else [value]
        unknown_values = {
            str(item) for item in values if item is not None
        } - definition.allowed_values
        if unknown_values:
            raise PolicyValidationError(
                f"Invalid value for policy dimension {dimension}: {sorted(unknown_values)[0]}"
            )
    return definition


def validate_partition(
    *,
    dimension: str,
    stage: PolicyDimensionStage | str,
    enforce: bool = True,
) -> PolicyDimension:
    definition = validate_dimension_stage(dimension=dimension, stage=stage, enforce=enforce)
    if not definition.partitionable:
        raise PolicyValidationError(f"Policy dimension {dimension} is not partitionable")
    return definition


def evaluate_matcher(
    *,
    subject: Mapping[str, Any],
    dimension: str,
    operator: PolicyMatcherOperator | str,
    stage: PolicyDimensionStage | str,
    value: Any = None,
) -> bool:
    validate_matcher(dimension=dimension, operator=operator, stage=stage, value=value)
    resolved_operator = PolicyMatcherOperator(operator)
    actual = subject.get(dimension)
    if actual is None:
        return resolved_operator == PolicyMatcherOperator.NOT_EXISTS
    if resolved_operator == PolicyMatcherOperator.EXISTS:
        return True
    if resolved_operator == PolicyMatcherOperator.NOT_EXISTS:
        return False
    if resolved_operator == PolicyMatcherOperator.EQ:
        return actual == value or str(actual) == str(value)
    if resolved_operator == PolicyMatcherOperator.IN:
        return actual in value or str(actual) in {str(item) for item in value}
    raise PolicyValidationError(f"Unsupported matcher operator: {operator}")


def to_dimension_snapshot(
    subject: Mapping[str, Any],
    *,
    stage: PolicyDimensionStage | str | None = None,
) -> dict[str, Any]:
    allowed_names = DIMENSIONS.keys()
    if stage is not None:
        allowed_names = STAGE_DIMENSION_NAMES[PolicyDimensionStage(stage)]
    return {
        name: (
            str(value)
            if value is not None and DIMENSIONS[name].value_type == PolicyDimensionType.UUID
            else value
        )
        for name, value in subject.items()
        if name in allowed_names and value is not None
    }
