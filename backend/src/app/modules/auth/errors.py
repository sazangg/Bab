class AuthError(RuntimeError):
    pass


class InvalidCredentialsError(AuthError):
    pass


class InvalidRefreshTokenError(AuthError):
    pass


class RefreshTokenReuseError(InvalidRefreshTokenError):
    """Raised when an already-rotated/revoked refresh token is replayed."""

    pass


class InvalidAccessTokenError(AuthError):
    pass


class LastOwnerError(AuthError):
    pass


class MemberNotFoundError(AuthError):
    pass


class MemberAlreadyExistsError(AuthError):
    pass


class MemberOrganizationConflictError(AuthError):
    """Raised when an account already belongs to a different organization."""

    pass


class PermissionDeniedError(AuthError):
    pass


class DuplicateInviteError(AuthError):
    pass


class InvalidInviteTargetError(AuthError):
    pass


class InviteNotFoundError(AuthError):
    pass


class InviteLifecycleError(AuthError):
    pass
