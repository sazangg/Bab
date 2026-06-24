class WorkspaceAccessDeniedError(Exception):
    pass


class WorkspaceScopeNotFoundError(Exception):
    def __init__(self, reason: str = "not_found") -> None:
        self.reason = reason
        super().__init__(reason)
