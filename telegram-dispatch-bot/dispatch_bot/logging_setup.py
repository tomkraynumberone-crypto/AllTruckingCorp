"""Logging to the console and to logs/bot.log. The bot token is always masked."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b")


class RedactSecrets(logging.Filter):
    def __init__(self, secrets=()):
        super().__init__()
        self.secrets = [s for s in secrets if s]

    def _clean(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "***")
        return _TOKEN_RE.sub("***", text)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._clean(record.getMessage())
        record.args = None
        if record.exc_info:  # make sure tracebacks cannot leak the token either
            record.exc_text = self._clean(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def setup_logging(cfg) -> None:
    level = getattr(logging, cfg.log_level, logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    redact = RedactSecrets([cfg.bot_token])

    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(redact)
    root.addHandler(console)

    Path(cfg.log_dir).mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(Path(cfg.log_dir) / "bot.log", maxBytes=1_000_000,
                                       backupCount=5, encoding="utf-8")
    file_handler.setFormatter(fmt)
    file_handler.addFilter(redact)
    root.addHandler(file_handler)
