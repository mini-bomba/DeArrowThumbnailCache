import pathlib
import socket
import time

from .config import get_config

config = get_config()
basedir = pathlib.Path("logs")


def log(*data: object) -> None:
    if config.debug:
        print(*data)


def log_error(*data: object) -> None:
    print(*data)


def create_log_file(category: str, *, ext: str = "log") -> pathlib.Path:
    log = basedir / socket.gethostname() / f"{category}-{round(time.time()*1000)}.{ext}"
    log.parent.mkdir(parents=True, exist_ok=True)
    return log
