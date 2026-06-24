class PolicySimulationError(Exception):
    """Base error for cross-kind policy simulation."""


class PolicySimulationPermissionError(PolicySimulationError):
    pass


class PolicySimulationValidationError(PolicySimulationError):
    pass
