from dataclasses import dataclass
from uuid import UUID

from app.modules.policies.dimensions import (
    PolicyDimensionStage,
    validate_matcher,
    validate_partition,
)
from app.modules.policies.errors import PolicyValidationError
from app.modules.policies.schemas import (
    FALLBACK_REASONS,
    AccessPolicyPublicModelInput,
    LimitPolicyRuleInput,
)

FALLBACKABLE_PROVIDER_REASONS = set(FALLBACK_REASONS)


@dataclass(frozen=True, slots=True)
class EffectiveAccessPolicyCandidate:
    provider_id: UUID
    credential_pool_id: UUID
    model_id: UUID

    @property
    def key(self) -> tuple[UUID, UUID, UUID]:
        return (self.provider_id, self.credential_pool_id, self.model_id)


@dataclass(frozen=True, slots=True)
class EffectiveAccessPolicyPublicModel:
    routing_mode: str
    fallback_on: list[str]
    max_route_attempts: int | None
    candidates: list[EffectiveAccessPolicyCandidate]

    def with_candidates(
        self,
        candidates: list[EffectiveAccessPolicyCandidate],
    ) -> "EffectiveAccessPolicyPublicModel":
        return EffectiveAccessPolicyPublicModel(
            routing_mode=self.routing_mode,
            fallback_on=self.fallback_on,
            max_route_attempts=self.max_route_attempts,
            candidates=candidates,
        )


def validate_access_policy_public_model_payload(
    public_models: list[AccessPolicyPublicModelInput],
) -> None:
    seen_names: set[str] = set()
    for public_model in public_models:
        normalized_name = public_model.public_model_name.strip()
        if normalized_name in seen_names:
            raise PolicyValidationError
        seen_names.add(normalized_name)
        if public_model.routing_mode == "single_route" and public_model.fallback_on:
            raise PolicyValidationError
        if public_model.routing_mode == "ordered_fallback":
            invalid_reasons = set(public_model.fallback_on) - FALLBACKABLE_PROVIDER_REASONS
            if invalid_reasons:
                raise PolicyValidationError
        seen_candidates: set[tuple[UUID, UUID, UUID]] = set()
        for candidate in public_model.candidates:
            candidate_key = (
                candidate.provider_id,
                candidate.credential_pool_id,
                candidate.model_offering_id,
            )
            if candidate_key in seen_candidates:
                raise PolicyValidationError
            seen_candidates.add(candidate_key)


def validate_scoped_access_policy_public_model_payload(
    *,
    public_models: list[AccessPolicyPublicModelInput],
    parent_public_models: dict[str, EffectiveAccessPolicyPublicModel],
) -> None:
    for public_model in public_models:
        parent = parent_public_models.get(public_model.public_model_name)
        if parent is None:
            raise PolicyValidationError
        if parent.routing_mode == "single_route" and public_model.routing_mode != "single_route":
            raise PolicyValidationError
        if public_model.routing_mode == "ordered_fallback":
            if parent.routing_mode != "ordered_fallback":
                raise PolicyValidationError
            if set(fallback_on_values(public_model)) - set(parent.fallback_on):
                raise PolicyValidationError
            if (
                public_model.max_route_attempts is not None
                and parent.max_route_attempts is not None
                and public_model.max_route_attempts > parent.max_route_attempts
            ):
                raise PolicyValidationError
        parent_candidate_positions = {
            candidate.key: index for index, candidate in enumerate(parent.candidates)
        }
        previous_position = -1
        for candidate in public_model.candidates:
            submitted = EffectiveAccessPolicyCandidate(
                provider_id=candidate.provider_id,
                credential_pool_id=candidate.credential_pool_id,
                model_id=candidate.model_offering_id,
            )
            position = parent_candidate_positions.get(submitted.key)
            if position is None or position < previous_position:
                raise PolicyValidationError
            previous_position = position


def validate_limit_rule_payload(payload: LimitPolicyRuleInput) -> None:
    if payload.limit_type == "tokens_per_request" and (
        payload.interval_unit != "lifetime" or payload.interval_count != 1
    ):
        raise PolicyValidationError
    if payload.limit_type == "tokens_per_request" and payload.partitions:
        raise PolicyValidationError
    seen_partition_positions: set[int] = set()
    seen_partition_dimensions: set[str] = set()
    for matcher in payload.matchers:
        try:
            validate_matcher(
                dimension=matcher.dimension,
                operator=matcher.operator,
                value=matcher.value_json,
                stage=PolicyDimensionStage.LIMIT_RESERVATION,
            )
        except (PolicyValidationError, ValueError) as exc:
            raise PolicyValidationError from exc
    for partition in payload.partitions:
        if partition.position in seen_partition_positions:
            raise PolicyValidationError
        if partition.dimension in seen_partition_dimensions:
            raise PolicyValidationError
        seen_partition_positions.add(partition.position)
        seen_partition_dimensions.add(partition.dimension)
        try:
            validate_partition(
                dimension=partition.dimension,
                stage=PolicyDimensionStage.LIMIT_RESERVATION,
            )
        except (PolicyValidationError, ValueError) as exc:
            raise PolicyValidationError from exc


def fallback_on_values(public_model: AccessPolicyPublicModelInput) -> list[str]:
    if public_model.routing_mode != "ordered_fallback":
        return []
    return public_model.fallback_on or sorted(FALLBACKABLE_PROVIDER_REASONS)
