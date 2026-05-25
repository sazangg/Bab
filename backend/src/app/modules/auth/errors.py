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
