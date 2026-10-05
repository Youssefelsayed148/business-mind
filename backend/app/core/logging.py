import logging
import sys

from pythonjsonlogger.json import JsonFormatter

from app.core.config import settings


def setup_logging() -> None:
    log_handler = logging.StreamHandler(sys.stdout)
    formatter = JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
    )
    log_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(settings.LOG_LEVEL.upper())
    root_logger.handlers.clear()
    root_logger.addHandler(log_handler)

    # httpx logs every request URL at INFO, and Graph API calls carry
    # client_secret / access tokens in the query string.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
