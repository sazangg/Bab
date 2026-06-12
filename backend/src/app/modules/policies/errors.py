class PolicyError(Exception):
    pass


class PolicyNotFoundError(PolicyError):
    pass


class PolicyValidationError(PolicyError):
    pass


class PolicyAssignmentConflictError(PolicyError):
    pass


class PolicyPermissionError(PolicyError):
    pass
