from __future__ import annotations

import logging
import sys

import structlog

from vidi_pr.config.operator import LoggingConfig


def setup_logging(config: LoggingConfig) -> None:
    level = getattr(logging, config.level)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    if config.format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
