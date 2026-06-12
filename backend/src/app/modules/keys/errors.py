class ProjectNotFoundError(Exception):
    pass


class ProjectSlugAlreadyExistsError(Exception):
    pass


class OrganizationInactiveError(Exception):
    pass


class ProjectInactiveError(Exception):
    pass


class ProjectAccessUnavailableError(Exception):
    def __init__(self, summary):
        self.summary = summary
        super().__init__(summary.blocking_code or "project access is unavailable")


class PolicyNotConfiguredError(ProjectAccessUnavailableError):
    pass


class SecretDeliveryDisabledError(Exception):
    pass


class VirtualKeyNotFoundError(Exception):
    pass


class VirtualKeyAlreadyRevokedError(Exception):
    pass


class VirtualKeyOverlapActiveError(Exception):
    def __init__(self, deprecated_at):
        self.deprecated_at = deprecated_at
        super().__init__("virtual key rotation overlap is still active")


class InvalidVirtualKeyError(Exception):
    pass


class AccessDeniedError(Exception):
    pass
