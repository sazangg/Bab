class GuardrailPolicyNotFoundError(Exception):
    pass


class GuardrailAssignmentNotFoundError(Exception):
    pass


class GuardrailAssignmentConflictError(Exception):
    pass


class GuardrailDeniedError(Exception):
    def __init__(self, *, detail: str, policy_id=None, rule_id=None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.policy_id = policy_id
        self.rule_id = rule_id
