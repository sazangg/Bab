from uuid import UUID


def assignment_scope_target_key(
    *,
    scope_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
) -> str:
    if scope_type == "org":
        return "org"
    if scope_type == "team" and team_id is not None:
        return f"team:{team_id}"
    if scope_type == "project" and project_id is not None:
        return f"project:{project_id}"
    if scope_type == "virtual_key" and virtual_key_id is not None:
        return f"virtual_key:{virtual_key_id}"
    raise ValueError("scope target key requires the matching scoped id")


def assignment_scope_specificity(scope_type: str) -> int:
    return {
        "org": 0,
        "team": 1,
        "project": 2,
        "virtual_key": 3,
    }.get(scope_type, -1)
