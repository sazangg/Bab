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


def classify_provider_failure(status_code: int) -> str:
    if status_code == 408 or status_code == 504:
        return "timeout"
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "provider_5xx"
    return "provider_error"


class ProviderUpstreamError(ProviderError):
    def __init__(
        self,
        *,
        status_code: int,
        body: dict | list | str | None,
        failure_reason: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.body = body
        self.failure_reason = failure_reason or classify_provider_failure(status_code)
        super().__init__(f"provider upstream returned {status_code}: {self.failure_reason}")
