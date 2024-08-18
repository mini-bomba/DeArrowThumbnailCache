import copy
import logging
import pathlib
import socket
import time

from uvicorn.config import LOG_LEVELS, LOGGING_CONFIG

from .config import get_config

config = get_config()
basedir = pathlib.Path("logs")


def create_log_file(category: str, *, ext: str = "log") -> pathlib.Path:
    log = basedir / socket.gethostname() / f"{category}-{round(time.time()*1000)}.{ext}"
    log.parent.mkdir(parents=True, exist_ok=True)
    return log


def logging_setup():
    log_level = LOG_LEVELS[config.log_level] if isinstance(config.log_level, str) else config.log_level

    logging_config = copy.deepcopy(LOGGING_CONFIG)

    logging_config["formatters"]["default"]["fmt"] = "%(levelprefix)s [%(name)s] %(message)s"
    logging_config["loggers"]["app"] = {
        "handlers": ["default"],
        "level": log_level,
    }
    logging_config["loggers"]["utils"] = logging_config["loggers"]["app"]
    logging_config["loggers"]["rq"] = logging_config["loggers"]["app"]

    logging.config.dictConfig(logging_config)
