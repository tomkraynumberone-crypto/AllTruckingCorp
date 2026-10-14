"""Output formatting. The /available format must stay exactly:
    Mohammad Ibrahim, 19237; Juan Miguel, will be available 2pm
"""

from __future__ import annotations

import re

TELEGRAM_LIMIT = 4000  # real limit is 4096; keep a safety margin


def clean_name(name: str) -> str:
    """Commas and semicolons are the list separators, so never allow them inside a name."""
    return re.sub(r"\s+", " ", re.sub(r"[,;]", " ", name or "")).strip() or "Unknown driver"


def entry_now(name: str, zip_code: str) -> str:
    return f"{clean_name(name)}, {zip_code}"


def entry_later(name: str, when: str) -> str:
    return f"{clean_name(name)}, will be available {when}"


def join_entries(entries: list[str]) -> str:
    return "; ".join(entries)


def chunk_entries(entries: list[str], limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Join entries with '; ' but split into several messages if the text would be too long."""
    chunks, current = [], ""
    for entry in entries:
        piece = entry if not current else f"; {entry}"
        if current and len(current) + len(piece) > limit:
            chunks.append(current)
            current, piece = "", entry
        current += piece
    if current:
        chunks.append(current)
    return chunks
