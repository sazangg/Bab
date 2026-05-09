class ProjectNotFoundError(Exception):
    pass


class ProjectProviderAccessNotFoundError(Exception):
    pass


class ModelAliasNotFoundError(Exception):
    pass


class ModelAliasAlreadyExistsError(Exception):
    pass


class VirtualKeyNotFoundError(Exception):
    pass


class InvalidVirtualKeyError(Exception):
    pass


class AccessDeniedError(Exception):
    pass
