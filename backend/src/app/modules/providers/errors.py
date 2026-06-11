class ProviderError(RuntimeError):
    pass


class ProviderNotFoundError(ProviderError):
    pass


class ProviderInactiveError(ProviderError):
    pass


class ProviderCredentialRequiredError(ProviderError):
    pass


class ProviderAdapterNotFoundError(ProviderError):
    pass


class ProviderSlugConflictError(ProviderError):
    pass


class ProviderResourceConflictError(ProviderError):
    pass


class ProviderUpstreamError(ProviderError):
    def __init__(self, *, status_code: int, body: dict | list | str | None) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"provider upstream returned {status_code}")
