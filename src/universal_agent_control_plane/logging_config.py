from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            event.update(fields)
        if record.exc_info:
            event["exception"] = self.formatException(record.exc_info)
        return json.dumps(event, ensure_ascii=True, separators=(",", ":"))


def configure_logging(data_dir: Path) -> None:
    level_name = os.environ.get("UACP_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        raise ValueError(f"Invalid UACP_LOG_LEVEL: {level_name}")

    data_dir.mkdir(parents=True, exist_ok=True)
    formatter = JsonFormatter()
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    log_file = RotatingFileHandler(
        data_dir / "server.log",
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    log_file.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(console)
    root.addHandler(log_file)
