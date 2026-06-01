class PolicyError(Exception):
    pass


class PolicyNotFoundError(PolicyError):
    pass


class PolicyValidationError(PolicyError):
    pass
