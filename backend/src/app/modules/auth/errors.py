class AuthError(RuntimeError):
    pass


class InvalidCredentialsError(AuthError):
    pass


class InvalidRefreshTokenError(AuthError):
    pass


class InvalidAccessTokenError(AuthError):
    pass


class LastOwnerError(AuthError):
    pass


class MemberNotFoundError(AuthError):
    pass


class MemberAlreadyExistsError(AuthError):
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
