class AuthError(RuntimeError):
    pass


class InvalidCredentialsError(AuthError):
    pass


class InvalidRefreshTokenError(AuthError):
    pass


class InvalidAccessTokenError(AuthError):
    pass
