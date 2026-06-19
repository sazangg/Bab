class GuardrailPolicyNotFoundError(Exception):
    pass


class GuardrailAssignmentNotFoundError(Exception):
    pass


class GuardrailAssignmentConflictError(Exception):
    pass


class GuardrailAssignmentTargetNotFoundError(Exception):
    pass


class GuardrailDeniedError(Exception):
    def __init__(
        self,
        *,
        detail: str,
        policy_id=None,
        policy_revision_id=None,
        assignment_id=None,
        assignment_mode=None,
        assignment_scope_type=None,
        assignment_team_id=None,
        assignment_project_id=None,
        assignment_virtual_key_id=None,
        rule_id=None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.policy_id = policy_id
        self.policy_revision_id = policy_revision_id
        self.assignment_id = assignment_id
        self.assignment_mode = assignment_mode
        self.assignment_scope_type = assignment_scope_type
        self.assignment_team_id = assignment_team_id
        self.assignment_project_id = assignment_project_id
        self.assignment_virtual_key_id = assignment_virtual_key_id
        self.rule_id = rule_id
