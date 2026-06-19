from uuid import uuid4

import pytest

from app.modules.policies.dimensions import (
    ATTEMPT_SCOPED_DIMENSIONS,
    DIMENSIONS,
    PolicyDimensionStage,
    PolicyMatcherOperator,
    evaluate_matcher,
    to_dimension_snapshot,
    validate_dimension_stage,
    validate_matcher,
    validate_partition,
)
from app.modules.policies.errors import PolicyValidationError


def test_dimension_registry_defines_initial_plan_dimensions() -> None:
    assert {
        "org_id",
        "team_id",
        "project_id",
        "virtual_key_id",
        "provider_id",
        "credential_pool_id",
        "provider_credential_id",
        "provider_model_offering_id",
        "public_model_id",
        "public_model_name",
        "route_candidate_id",
        "access_policy_id",
        "access_policy_revision_id",
        "gateway_endpoint",
        "requested_model",
        "streaming",
        "catalog_entry_id",
        "model_family",
        "input_modality",
        "output_modality",
    } <= DIMENSIONS.keys()

    assert DIMENSIONS["provider_credential_id"].stages == frozenset(
        {
            PolicyDimensionStage.PROVIDER_ATTEMPT,
            PolicyDimensionStage.RESPONSE_GUARDRAIL,
            PolicyDimensionStage.LIMIT_COMMIT,
        }
    )
    assert "provider_id" in ATTEMPT_SCOPED_DIMENSIONS
    assert "project_id" not in ATTEMPT_SCOPED_DIMENSIONS


def test_dimension_stage_validation_rejects_unavailable_enforced_dimensions() -> None:
    with pytest.raises(PolicyValidationError):
        validate_dimension_stage(
            dimension="provider_id",
            stage=PolicyDimensionStage.ACCESS_RESOLUTION,
        )

    assert (
        validate_dimension_stage(
            dimension="provider_id",
            stage=PolicyDimensionStage.ACCESS_RESOLUTION,
            enforce=False,
        ).name
        == "provider_id"
    )


def test_matcher_validation_rejects_unknown_dimensions_and_invalid_values() -> None:
    with pytest.raises(PolicyValidationError):
        validate_matcher(
            dimension="unknown_dimension",
            operator=PolicyMatcherOperator.EQ,
            stage=PolicyDimensionStage.LIMIT_RESERVATION,
            value="x",
        )

    with pytest.raises(PolicyValidationError):
        validate_matcher(
            dimension="project_id",
            operator=PolicyMatcherOperator.IN,
            stage=PolicyDimensionStage.LIMIT_RESERVATION,
            value="not-a-list",
        )

    with pytest.raises(PolicyValidationError):
        validate_matcher(
            dimension="gateway_endpoint",
            operator=PolicyMatcherOperator.EQ,
            stage=PolicyDimensionStage.PRE_RESOLUTION,
            value="unknown_endpoint",
        )


@pytest.mark.parametrize(
    "endpoint",
    ["completions", "chat_completions", "responses", "anthropic_messages"],
)
def test_gateway_endpoint_dimension_accepts_runtime_values(endpoint: str) -> None:
    validate_matcher(
        dimension="gateway_endpoint",
        operator=PolicyMatcherOperator.EQ,
        stage=PolicyDimensionStage.PRE_RESOLUTION,
        value=endpoint,
    )


def test_matcher_unknown_value_semantics() -> None:
    subject = {"project_id": str(uuid4())}

    assert not evaluate_matcher(
        subject=subject,
        dimension="provider_id",
        operator=PolicyMatcherOperator.EQ,
        stage=PolicyDimensionStage.LIMIT_RESERVATION,
        value=str(uuid4()),
    )
    assert not evaluate_matcher(
        subject=subject,
        dimension="provider_id",
        operator=PolicyMatcherOperator.EXISTS,
        stage=PolicyDimensionStage.LIMIT_RESERVATION,
    )
    assert evaluate_matcher(
        subject=subject,
        dimension="provider_id",
        operator=PolicyMatcherOperator.NOT_EXISTS,
        stage=PolicyDimensionStage.LIMIT_RESERVATION,
    )


def test_matcher_value_semantics() -> None:
    project_id = str(uuid4())
    subject = {
        "project_id": project_id,
        "public_model_name": "fast-general",
    }

    assert evaluate_matcher(
        subject=subject,
        dimension="project_id",
        operator=PolicyMatcherOperator.EQ,
        stage=PolicyDimensionStage.LIMIT_RESERVATION,
        value=project_id,
    )
    assert evaluate_matcher(
        subject=subject,
        dimension="public_model_name",
        operator=PolicyMatcherOperator.IN,
        stage=PolicyDimensionStage.LIMIT_RESERVATION,
        value=["fast-general", "cheap"],
    )
    assert not evaluate_matcher(
        subject=subject,
        dimension="public_model_name",
        operator=PolicyMatcherOperator.NOT_EXISTS,
        stage=PolicyDimensionStage.LIMIT_RESERVATION,
    )


def test_matcher_uuid_values_can_be_json_strings() -> None:
    project_id = uuid4()

    assert evaluate_matcher(
        subject={"project_id": project_id},
        dimension="project_id",
        operator=PolicyMatcherOperator.EQ,
        stage=PolicyDimensionStage.LIMIT_RESERVATION,
        value=str(project_id),
    )
    assert evaluate_matcher(
        subject={"project_id": project_id},
        dimension="project_id",
        operator=PolicyMatcherOperator.IN,
        stage=PolicyDimensionStage.LIMIT_RESERVATION,
        value=[str(project_id)],
    )


def test_partition_validation_uses_stage_availability() -> None:
    assert (
        validate_partition(
            dimension="provider_id",
            stage=PolicyDimensionStage.LIMIT_RESERVATION,
        ).name
        == "provider_id"
    )

    with pytest.raises(PolicyValidationError):
        validate_partition(
            dimension="provider_credential_id",
            stage=PolicyDimensionStage.LIMIT_RESERVATION,
        )


def test_dimension_snapshot_filters_by_stage_and_serializes_uuid_values() -> None:
    project_id = uuid4()
    provider_credential_id = uuid4()

    assert to_dimension_snapshot(
        {
            "project_id": project_id,
            "provider_credential_id": provider_credential_id,
            "unknown": "ignored",
            "streaming": False,
        },
        stage=PolicyDimensionStage.LIMIT_RESERVATION,
    ) == {
        "project_id": str(project_id),
        "streaming": False,
    }
