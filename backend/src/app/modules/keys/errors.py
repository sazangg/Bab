class ProjectNotFoundError(Exception):
    pass


class PolicyNotConfiguredError(Exception):
    pass


class VirtualKeyNotFoundError(Exception):
    pass


class InvalidVirtualKeyError(Exception):
    pass


class AccessDeniedError(Exception):
    pass
