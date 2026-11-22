import json
import os
import time
from pathlib import Path

STATUS_DIR = Path("logs/status")
AGENT_HEARTBEAT = STATUS_DIR / "agent.json"


def write_status(path, **fields):
    path = Path(path)
    for _ in range(3):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(fields), encoding="utf-8")
            os.replace(tmp, path)
            return
        except OSError:
            time.sleep(0.1)


def read_status(path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def update_status(path, **fields):
    data = read_status(path)
    data.update(fields)
    write_status(path, **data)
