import json
from datetime import datetime
from pathlib import Path

CACHE_DIR = Path("data/cache")


class CacheManager:

    def __init__(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _target_dir(self, target: str) -> Path:
        safe = target.replace(".", "_").replace(":", "_")
        d = CACHE_DIR / safe
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write(self, target: str, data_type: str, content) -> Path:
        d = self._target_dir(target)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        payload = {"target": target, "type": data_type, "timestamp": timestamp, "content": content}

        dated = d / f"{data_type}_{timestamp}.json"
        latest = d / f"latest_{data_type}.json"
        dated.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        latest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return latest

    def read_latest(self, target: str, data_type: str):
        latest = self._target_dir(target) / f"latest_{data_type}.json"
        if not latest.exists():
            return None
        try:
            return json.loads(latest.read_text(encoding="utf-8"))
        except Exception:
            return None

    def age_seconds(self, target: str, data_type: str) -> float:
        cached = self.read_latest(target, data_type)
        if not cached:
            return -1
        try:
            ts = datetime.strptime(cached["timestamp"], "%Y%m%d_%H%M%S")
            return (datetime.now() - ts).total_seconds()
        except Exception:
            return -1

    def list_targets(self) -> list:
        if not CACHE_DIR.exists():
            return []
        return [p.name for p in CACHE_DIR.iterdir() if p.is_dir()]
