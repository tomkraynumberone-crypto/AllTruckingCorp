"""Start the bot:  python -m dispatch_bot"""

from __future__ import annotations

import asyncio
import logging
import sys

from .config import ConfigError, load_config
from .logging_setup import setup_logging


def main() -> int:
    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"\nConfiguration problem: {exc}\n\nOpen the .env file, fix it, and start again.")
        return 1
    setup_logging(cfg)
    log = logging.getLogger("dispatch_bot")
    try:
        from .telegram_app import run_bot
        asyncio.run(run_bot(cfg))
    except ImportError as exc:
        log.error("A required package is missing (%s). Run setup.bat again.", exc)
        return 1
    except KeyboardInterrupt:
        log.info("Stopped by user.")
    except Exception:
        log.exception("The bot stopped because of an error.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
