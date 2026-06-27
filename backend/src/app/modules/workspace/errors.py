class ProjectNotFoundError(Exception):
    pass


class TeamNotFoundError(Exception):
    pass


class TeamInactiveError(Exception):
    pass


class TeamSlugAlreadyExistsError(Exception):
    pass


class ProjectSlugAlreadyExistsError(Exception):
    pass


class OrganizationInactiveError(Exception):
    pass


class ProjectInactiveError(Exception):
    pass


class WorkspaceAccessDeniedError(Exception):
    pass


class WorkspaceScopeNotFoundError(Exception):
    def __init__(self, reason: str = "not_found") -> None:
        self.reason = reason
        super().__init__(reason)
