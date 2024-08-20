import copy
import logging
import pathlib
import socket
import sys
import time

from uvicorn.config import LOG_LEVELS, LOGGING_CONFIG

from .config import get_config

config = get_config()
basedir = pathlib.Path("logs")


class SwitchingHandler(logging.Handler):
    """
    This handler logs low-severity entries to one handler and high-severity another. (for example stdout and stderr)

    Intended for use in podman containers, to stop flooding the journal with info logs as errors.
    """
    threshold: int
    low_handler: logging.Handler
    high_handler: logging.Handler

    def __init__(
        self,
        threshold_level=logging.WARNING, *,
        low_handler: logging.Handler | None = None,
        high_handler: logging.Handler | None = None
    ):
        super().__init__()
        self.threshold = threshold_level
        self.low_handler = low_handler if low_handler is not None else logging.StreamHandler(sys.stdout)
        self.high_handler = high_handler if high_handler is not None else logging.StreamHandler(sys.stderr)

    def emit(self, record: logging.LogRecord):
        if record.levelno >= self.threshold:
            self.high_handler.handle(record)
        else:
            self.low_handler.handle(record)

    def setFormatter(self, fmt: logging.Formatter):
        self.high_handler.setFormatter(fmt)
        self.low_handler.setFormatter(fmt)


def create_log_file(category: str, *, ext: str = "log") -> pathlib.Path:
    log = basedir / socket.gethostname() / f"{category}-{round(time.time()*1000)}.{ext}"
    log.parent.mkdir(parents=True, exist_ok=True)
    return log


def logging_setup():
    log_level = LOG_LEVELS[config.log_level] if isinstance(config.log_level, str) else config.log_level
    stderr_threshold = LOG_LEVELS[config.stderr_threshold] if isinstance(config.stderr_threshold, str) else config.stderr_threshold

    logging_config = copy.deepcopy(LOGGING_CONFIG)

    logging_config["formatters"]["default"]["fmt"] = "%(levelprefix)s [%(name)s] %(message)s"
    logging_config["loggers"]["app"] = {
        "handlers": ["default"],
        "level": log_level,
    }
    logging_config["loggers"]["utils"] = logging_config["loggers"]["app"]
    logging_config["loggers"]["rq"] = logging_config["loggers"]["app"]
    logging_config["handlers"]["default"]["class"] = "utils.logger.SwitchingHandler"
    del logging_config["handlers"]["default"]["stream"]
    logging_config["handlers"]["default"]["threshold_level"] = stderr_threshold

    logging.config.dictConfig(logging_config)
