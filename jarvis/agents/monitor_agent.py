
import threading
import time
import json
import os
from datetime import datetime
from pathlib import Path
from agents.base_agent import BaseAgent
from tools.cache_manager import CacheManager

DEFAULT_INTERVAL = 60

MONITOR_COMMANDS = {
    "failed_logins":   "sudo grep 'Failed password' /var/log/auth.log | tail -30",
    "active_users":    "who",
    "open_ports":      "sudo ss -tlnp",
    "firewall_status": "sudo ufw status",
    "cpu_usage":       "top -bn1 | grep 'Cpu(s)'",
    "memory_usage":    "free -h",
    "disk_usage":      "df -h /",
    "last_logins":     "last -n 5",
    "sudo_activity":   "sudo grep 'sudo' /var/log/auth.log | tail -10",
    "network_conns":   "sudo ss -tnp | grep ESTABLISHED",
}

SYSTEM_PROMPT = """You are a SOC Tier-1 analyst. Write concise, professional security
incident reports. Use severity labels: CRITICAL / HIGH / MEDIUM / LOW / INFO.
Always include recommended actions. Be direct."""


class MonitorAgent(BaseAgent):

    def __init__(self, memory, mcp, vm_ip="192.168.48.128", vm_user="ivansdp"):
        super().__init__(memory, mcp)
        self.vm_ip       = memory.recall("vm_ip") or vm_ip
        self.vm_user     = memory.recall("vm_user") or vm_user
        self._running    = False
        self._thread     = None
        self._interval   = DEFAULT_INTERVAL
        self._history    = []
        self.log_dir     = Path("logs/monitor")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.cache       = CacheManager()

    def _ssh(self, command: str) -> str:
        pwd = self.memory.recall(f"vm_password_{self.vm_ip.replace('.', '_')}") or ""
        if not pwd:
            return "No VM password cached. Run 'security audit' first."
        r = self.mcp.ssh_exec(self.vm_ip, self.vm_user, pwd, command, timeout=20)
        return r["stdout"] or r["stderr"]

    def _collect(self) -> dict:
        snapshot = {"timestamp": datetime.now().isoformat(), "vm": self.vm_ip, "data": {}}
        for name, cmd in MONITOR_COMMANDS.items():
            snapshot["data"][name] = self._ssh(cmd)
        self.cache.write(self.vm_ip, "monitor_snapshot", snapshot["data"])
        return snapshot

    def _detect_threats(self, snapshot: dict) -> list:
        threats = []
        data    = snapshot["data"]
        failed  = data.get("failed_logins", "")

        if failed.count("Failed password") >= 5:
            threats.append({"severity": "HIGH", "type": "Brute Force Attack",
                            "detail": f"{failed.count('Failed password')} failed logins"})
        if "Failed password for root" in failed:
            threats.append({"severity": "CRITICAL", "type": "Root Login Attempt",
                            "detail": "SSH root login attempted"})
        if failed.count("Invalid user") >= 3:
            threats.append({"severity": "MEDIUM", "type": "Invalid User Attempts",
                            "detail": f"{failed.count('Invalid user')} unknown username attempts"})
        if "inactive" in data.get("firewall_status", "").lower():
            threats.append({"severity": "HIGH", "type": "Firewall Inactive",
                            "detail": "UFW is OFF"})
        active = data.get("active_users", "").strip()
        if active:
            threats.append({"severity": "INFO", "type": "Active Session", "detail": active[:80]})
        return threats

    def _generate_report(self, snapshot: dict, threats: list) -> str:
        threat_text = "\n".join(f"[{t['severity']}] {t['type']}: {t['detail']}" for t in threats) or "No active threats."
        prompt = f"""SOC Report — {self.vm_ip} — {snapshot['timestamp']}
THREATS:
{threat_text}
PERFORMANCE: CPU {snapshot['data'].get('cpu_usage','N/A')} | MEM {snapshot['data'].get('memory_usage','N/A')}
Write a short SOC report: Summary, Threat Assessment, Recommended Actions, Overall Risk Level."""
        return self.llm(prompt, system=SYSTEM_PROMPT, max_tokens=500)

    def _poll(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        print(f"\n  [MONITOR] Polling {self.vm_ip}...", end=" ", flush=True)
        try:
            snapshot = self._collect()
            threats  = self._detect_threats(snapshot)
            self._history.append({"time": timestamp, "threats": threats})

            if threats or len(self._history) % 5 == 0:
                report = self._generate_report(snapshot, threats)
                (self.log_dir / f"report_{timestamp}.txt").write_text(report, encoding="utf-8")
                self.memory.log_agent("monitor", f"poll_{timestamp}", report[:400])
                if threats:
                    print(f"{len(threats)} THREAT(S)")
                    for t in threats:
                        print(f"    [{t['severity']}] {t['type']}: {t['detail']}")
                else:
                    print("clear (report saved)")
            else:
                print("clear")
        except Exception as e:
            print(f"ERROR: {e}")

    def _monitor_loop(self):
        while self._running:
            self._poll()
            for _ in range(self._interval):
                if not self._running:
                    break
                time.sleep(1)

    def start(self, interval: int = DEFAULT_INTERVAL) -> str:
        if self._running:
            return f"Monitor already running every {self._interval}s."
        self._running  = True
        self._interval = interval
        self._thread   = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        return f"Monitor STARTED — polling {self.vm_ip} every {interval}s\nType 'stop monitor' to stop."

    def stop(self) -> str:
        self._running = False
        return "Monitor STOPPED. SSH connections closed."

    def status(self) -> str:
        if not self._running:
            return "Monitor not running. Type 'start monitor' to begin."
        recent = self._history[-5:]
        lines  = [f"Monitor RUNNING — every {self._interval}s | Total polls: {len(self._history)}"]
        for h in reversed(recent):
            ts = f"{len(h['threats'])} threat(s)" if h['threats'] else "clear"
            lines.append(f"  {h['time']}: {ts}")
        return "\n".join(lines)

    def get_latest_report(self) -> str:
        reports = sorted(self.log_dir.glob("report_*.txt"))
        if not reports:
            return "No reports yet. Run 'start monitor' or 'security audit'."
        return reports[-1].read_text(encoding="utf-8")

    def run(self, task: str) -> str:
        low = task.lower()
        if any(k in low for k in ["start monitor", "begin monitor", "monitor start", "monitor the vm", "continuous", "background monitor"]):
            import re
            m = re.search(r'every (\d+)', low)
            return self.start(int(m.group(1)) if m else DEFAULT_INTERVAL)
        elif any(k in low for k in ["stop monitor", "monitor stop"]):
            return self.stop()
        elif any(k in low for k in ["monitor status", "is monitor running"]):
            return self.status()
        elif any(k in low for k in ["latest report", "last report", "show report", "show latest"]):
            return self.get_latest_report()
        else:
            snap    = self._collect()
            threats = self._detect_threats(snap)
            return self._generate_report(snap, threats)
