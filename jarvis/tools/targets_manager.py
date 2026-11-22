import json
import re


class TargetsManager:

    KEY = "targets_registry"

    def __init__(self, memory):
        self.memory = memory

    def _load(self) -> dict:
        raw = self.memory.recall(self.KEY)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _save(self, data: dict):
        self.memory.store(self.KEY, json.dumps(data))

    def add(self, name: str, ip: str, user: str, framework: str = None) -> str:
        data = self._load()
        data[name.lower()] = {"ip": ip, "user": user, "framework": framework}
        self._save(data)
        fw = f" (audits framed for {framework})" if framework else ""
        return f"Added target '{name}' -> {user}@{ip}{fw}"

    def remove(self, name: str) -> str:
        data = self._load()
        if name.lower() in data:
            del data[name.lower()]
            self._save(data)
            return f"Removed target '{name}'"
        return f"No target named '{name}'"

    def get(self, name_or_ip: str):
        data = self._load()
        key = name_or_ip.lower()
        if key in data:
            return {"name": key, **data[key]}

        if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', name_or_ip):
            for name, info in data.items():
                if info["ip"] == name_or_ip:
                    return {"name": name, **info}
            return {"name": name_or_ip, "ip": name_or_ip, "user": None}
        return None

    def all(self) -> dict:
        return self._load()

    def list_str(self) -> str:
        data = self._load()
        if not data:
            return "No additional computers registered. The primary VM is always available."
        lines = [f"  {name}: {info['user']}@{info['ip']}" + (f"  [{info['framework']}]" if info.get("framework") else "")
                 for name, info in data.items()]
        return "Registered computers:\n" + "\n".join(lines)

    def parse_add_command(self, task: str):
        ip_match   = re.search(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b', task)
        name_match = re.search(r'\bas ([\w-]+)', task, re.IGNORECASE)
        user_match = re.search(r'\buser (\w+)', task, re.IGNORECASE)
        if not ip_match:
            return None
        ip   = ip_match.group(1)
        name = name_match.group(1) if name_match else ip.replace(".", "_")
        user = user_match.group(1) if user_match else "root"
        return name, ip, user
