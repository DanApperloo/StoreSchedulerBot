class SingletonError(Exception):
    pass


class SingletonNotExist(SingletonError):
    pass


class SingletonExist(SingletonError):
    pass


class ConfigError(Exception):
    pass
