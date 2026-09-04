"""Central logging configuration."""

import logging
from logging.config import dictConfig


def setup_logging(level: str = "INFO") -> None:
    normalized = level.upper()
    if normalized not in logging._nameToLevel:
        normalized = "INFO"

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "level": normalized,
                }
            },
            "root": {"handlers": ["console"], "level": normalized},
        }
    )
