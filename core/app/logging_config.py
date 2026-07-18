from __future__ import annotations

import logging
import logging.handlers

import structlog

from app.config import Settings

LOG_FILENAME = "core.log"
LOG_MAX_BYTES = 10 * 1024 * 1024  # Kap. 9.1: 10 MB x 5 Dateien
LOG_BACKUP_COUNT = 5


def configure_logging(settings: Settings) -> None:
    """Structured logging (Kap. 9.1): a rotating JSON file under the app's
    own data directory (`logs/core.log`), plus a human-readable console
    stream. The file exists specifically so a problem can be diagnosed after
    the fact -- copy its contents (or the tail of it) into a bug report --
    without having needed to be watching a console at the exact moment
    something went wrong, which `cargo tauri dev` often doesn't show anyway.
    """
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = settings.logs_dir / LOG_FILENAME

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(processor=structlog.dev.ConsoleRenderer())
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(processor=structlog.processors.JSONRenderer())
    )

    root_logger = logging.getLogger()
    root_logger.handlers = [console_handler, file_handler]
    root_logger.setLevel(logging.INFO)

    structlog.get_logger(__name__).info("logging_configured", log_file=str(log_path))
