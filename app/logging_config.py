"""Structured logging configuration using structlog.

Provides a single ``configure_logging`` entry-point that sets up structlog
processors and configures the stdlib root logger to emit structured JSON
(production) or human-readable console output (development).
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(*, json_logs: bool = True, log_level: str = "INFO") -> None:
    """Configure structlog and the stdlib root logger.

    Args:
        json_logs: When *True* (default / production), render logs as JSON.
            When *False* (development), use a colourful console renderer.
        log_level: Root log level name (e.g. ``"INFO"``, ``"DEBUG"``).
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level.upper())
