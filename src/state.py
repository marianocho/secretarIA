"""Persistência do last_update_id pra catchup do backlog do Telegram.

Escrita atômica via os.replace() pra não corromper o arquivo se o processo
morrer no meio.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from src import config


def load_last_update_id() -> int | None:
    path = config.STATE_FILE_PATH
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    value = data.get("last_update_id")
    return int(value) if value is not None else None


def save_last_update_id(update_id: int) -> None:
    path = config.STATE_FILE_PATH
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps({"last_update_id": update_id}), encoding="utf-8")
    os.replace(tmp, path)
