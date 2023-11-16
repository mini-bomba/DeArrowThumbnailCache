from .config import get_config

config = get_config()

def log(*data: object) -> None:
    if config.debug:
        print(*data)

def log_error(*data: object) -> None:
    print(*data)
