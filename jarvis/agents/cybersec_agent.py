
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from agents.base_agent import BaseAgent
from tools.cache_manager import CacheManager
from tools.targets_manager import TargetsManager
from tools.status_board import write_status, update_status

VM_IP   = "192.168.48.128"
VM_USER = "ivansdp"

AUDIT_COMMANDS = {
    "firewall_status":    "sudo ufw status verbose",
    "open_ports":         "sudo netstat -tuln",
    "active_users":       "who",
    "failed_logins":      "sudo grep 'Failed password' /var/log/auth.log | tail -20",
    "successful_logins":  "sudo grep 'Accepted' /var/log/auth.log | tail -20",
    "running_services":   "sudo systemctl list-units --type=service --state=running",
    "sudo_attempts":      "sudo grep 'sudo' /var/log/auth.log | tail -10",
    "user_accounts":      "cat /etc/passwd | grep -v nologin | grep -v false",
    "sudo_users":         "getent group sudo",
    "last_logins":        "last -n 10",
    "cpu_usage":          "top -bn1 | grep 'Cpu(s)'",
    "memory_usage":       "free -h",
    "disk_usage":         "df -h",
    "installed_packages": "dpkg -l | grep -E '(ssh|ufw|fail2ban|netcat|nmap)' 2>/dev/null",
    "network_conns":      "sudo ss -tnp | grep ESTABLISHED",
}

REMEDIATION = {
    "enable_firewall": "sudo ufw --force enable",
    "default_deny":    "sudo ufw default deny incoming",
    "allow_ssh":       "sudo ufw allow ssh",
}


COMPUTE_COMMANDS = {
    "cpu_cores": "nproc",
    "mem_total": "grep MemTotal /proc/meminfo",
}


FRAMEWORKS = {
    "cis": {
        "name": "CIS Controls v8", "short": "CIS",
        "map": ("- Firewall, open ports, running services -> Control 4 (Secure Configuration; 4.4 firewall on servers, 4.8 disable unnecessary services), Control 12 (Network Infrastructure Management)\n"
                "- User accounts, sudo/admin access -> Control 5 (Account Management), Control 6 (Access Control Management)\n"
                "- Auth/system logs, failed logins -> Control 8 (Audit Log Management), Control 13 (Network Monitoring and Defense)\n"
                "- Installed packages, patching -> Control 7 (Continuous Vulnerability Management)"),
    },
    "nist": {
        "name": "NIST Cybersecurity Framework 2.0", "short": "NIST CSF",
        "map": ("- Firewall, open ports, services -> PR.PS (Platform Security), PR.IR (Technology Infrastructure Resilience)\n"
                "- Accounts, sudo, authentication -> PR.AA (Identity Management, Authentication, and Access Control)\n"
                "- Logs, failed logins, active sessions -> DE.CM (Continuous Monitoring), DE.AE (Adverse Event Analysis)\n"
                "- Packages, vulnerabilities -> ID.RA (Risk Assessment)\n"
                "- CPU/memory/disk usage -> PR.IR, DE.CM"),
    },
    "iso27001": {
        "name": "ISO/IEC 27001:2022 (Annex A)", "short": "ISO 27001",
        "map": ("- Firewall, open ports, services -> A.8.20 (Networks security), A.8.9 (Configuration management)\n"
                "- Accounts, sudo, authentication -> A.8.2 (Privileged access rights), A.8.5 (Secure authentication)\n"
                "- Logs, failed logins -> A.8.15 (Logging), A.8.16 (Monitoring activities)\n"
                "- Packages, patching -> A.8.8 (Management of technical vulnerabilities)"),
    },
    "soc2": {
        "name": "SOC 2 (Security criteria)", "short": "SOC 2",
        "map": ("- Firewall, open ports, services -> CC6.6 (boundary protection), CC6.1 (logical access)\n"
                "- Accounts, sudo, authentication -> CC6.1 (logical access security)\n"
                "- Logs, failed logins, active sessions -> CC7.2 (monitoring for anomalies), CC7.3 (evaluating security events)\n"
                "- Packages, vulnerabilities -> CC7.1 (vulnerability detection), CC6.8 (unauthorized or malicious software)"),
    },
    "pci": {
        "name": "PCI DSS v4.0", "short": "PCI DSS",
        "map": ("- Firewall, open ports, services -> Requirement 1 (network security controls), Requirement 2 (secure configurations, disable unnecessary services)\n"
                "- Accounts, sudo, authentication -> Requirement 7 (restrict access by need to know), Requirement 8 (identify users and authenticate)\n"
                "- Logs, failed logins -> Requirement 10 (log and monitor all access)\n"
                "- Packages, patching -> Requirement 6 (secure systems and software), Requirement 11 (test security regularly)"),
    },
    "hipaa": {
        "name": "HIPAA Security Rule (technical safeguards, 45 CFR 164.312)", "short": "HIPAA",
        "map": ("- Firewall, open ports, services -> 164.312(e) (transmission security), 164.312(a) (access control)\n"
                "- Accounts, sudo, logins -> 164.312(a) (access control), 164.312(d) (person or entity authentication)\n"
                "- Logs, failed logins -> 164.312(b) (audit controls)"),
    },
}

FRAMEWORK_PATTERNS = [
    ("cis",      r"\bcis\b"),
    ("nist",     r"\bnist\b"),
    ("iso27001", r"\biso\b|\b27001\b"),
    ("soc2",     r"\bsoc\s*-?\s*2\b"),
    ("pci",      r"\bpci\b"),
    ("hipaa",    r"\bhipaa\b"),
]


SSH_PORT = 22
PREFLIGHT_TIMEOUT = 45


def tcp_probe(ip: str, port: int = SSH_PORT, timeout: float = 5.0) -> str:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return "open"
    except ConnectionRefusedError:
        return "refused"
    except OSError:
        return "no answer"


LLM_ERRORS = ("Cannot connect to Ollama", "Ollama timed out", "LLM error:", "No response")

PLINK_HINT = ("plink isn't installed, so the agent can't SSH from Windows.\n"
              "Install it with: winget install PuTTY.PuTTY   (then restart PowerShell)")


def _is_windows() -> bool:
    return os.name == "nt"


def detect_framework(text: str):
    low = text.lower()
    for key, pattern in FRAMEWORK_PATTERNS:
        if re.search(pattern, low):
            return key
    return None


def find_ip(text: str):
    m = re.search(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b", text)
    if not m:
        return None, True
    return m.group(0), all(int(x) <= 255 for x in m.groups())


def compute_profile(cores_raw: str, mem_raw: str):
    c = re.search(r"\d+", cores_raw or "")
    m = re.search(r"MemTotal:\s+(\d+)\s*kB", mem_raw or "")
    if not c or not m:
        return "unknown", None, "Compute profile unavailable — give general recommendations."
    cores, mb = int(c.group()), int(m.group(1)) // 1024
    if cores <= 1 or mb < 2048:
        tier = "low"
    elif cores >= 8 and mb >= 16384:
        tier = "high"
    else:
        tier = "moderate"
    guidance = {
        "low":      "Low-resource host: recommend only lightweight controls (ufw, fail2ban, unattended-upgrades); avoid heavy agents.",
        "moderate": "Mid-size host: ufw + fail2ban + auditd are reasonable; avoid full SIEM agents.",
        "high":     "High-capacity host: heavier tooling (auditd, file-integrity monitoring, a log-forwarding agent) is reasonable.",
    }[tier]
    return f"{cores} CPU core(s), {mb} MB RAM ({tier} compute)", tier, guidance


SYSTEM_PROMPT = """You are an expert SOC (Security Operations Center) cybersecurity analyst.
When given security scan results:
1. Identify vulnerabilities — rate each: CRITICAL / HIGH / MEDIUM / LOW / INFO
2. Explain each risk in plain English
3. Provide exact Linux commands to fix each issue
4. Write like a professional SOC analyst, be concise
5. Give an overall risk score out of 10"""


class CyberSecAgent(BaseAgent):

    def __init__(self, memory, mcp):
        super().__init__(memory, mcp)
        self.vm_ip     = memory.recall("vm_ip") or VM_IP
        self.vm_user   = memory.recall("vm_user") or VM_USER
        self.cache     = CacheManager()
        self.targets   = TargetsManager(memory)

        self.current_ip   = self.vm_ip
        self.current_user = self.vm_user

        self.status_file  = None
        self.attempt      = 1
        self._last_touch  = 0.0
        self._session_pw  = {}


    def _status(self, state: str, detail: str = "", fresh: bool = False, **extra):
        if not self.status_file:
            return
        fields = dict(state=state, detail=detail, attempt=self.attempt, pid=os.getpid(),
                      target=self.current_ip, progress=time.time(), **extra)
        (write_status if fresh else update_status)(self.status_file, **fields)

    def touch_progress(self):
        now = time.time()
        if self.status_file and now - self._last_touch > 2:
            self._last_touch = now
            update_status(self.status_file, progress=now)


    def _resolve_target(self, task: str):
        low = task.lower()
        self.current_ip, self.current_user = self.vm_ip, self.vm_user
        self.ip_given = False
        for name, info in self.targets.all().items():
            if re.search(rf"\b{re.escape(name)}\b", low):
                self.current_ip, self.current_user = info["ip"], info["user"]
                self.ip_given = True
                return name, None
        ip, valid = find_ip(task)
        if ip and not valid:
            return None, f"'{ip}' isn't a valid IP address (each part must be 0-255). Example: security audit 192.168.48.128"
        if ip:
            self.current_ip = ip
            self.ip_given = True
            registered = next((i for i in self.targets.all().values() if i["ip"] == ip), None)
            if registered:
                self.current_user = registered["user"]
            u = re.search(r"\buser(?:name)?\s*[=:]?\s*([A-Za-z_][\w.-]*)", task, re.IGNORECASE)
            if u:
                self.current_user = u.group(1)
            return ip, None
        return "primary", None

    def _default_framework(self, ip: str):
        for info in self.targets.all().values():
            if info["ip"] == ip and info.get("framework") in FRAMEWORKS:
                return info["framework"]
        return None

    def _password_key(self) -> str:
        safe = self.current_ip.replace(".", "_")
        return f"vm_password_{safe}"

    def _get_password(self) -> str:
        key = self._password_key()
        stored = self.memory.recall(key) or self._session_pw.get(key)
        if stored:
            return stored
        try:
            self._status("waiting", f"waiting for the password for {self.current_user}@{self.current_ip} "
                                    f"to be typed in the audit window", waiting=True)
            pwd = input(f"\n  Password for {self.current_user}@{self.current_ip}: ")
            if self.safe_input("  Save password to memory? [y/n]: ") == "y":
                self.memory.store(key, pwd)
            self._session_pw[key] = pwd
            self._status("starting", "connecting to the computer", waiting=False)
            return pwd
        except (EOFError, KeyboardInterrupt):
            print("\n  Password input cancelled.")
            return ""


    def _ssh_raw(self, command: str, timeout: int = 25) -> dict:
        password = self._get_password()
        if not password:
            return {"stdout": "", "stderr": "No password provided", "success": False, "missing": False}
        return self.mcp.ssh_exec(self.current_ip, self.current_user, password, command, timeout=timeout)

    def _ssh(self, command: str) -> str:
        r = self._ssh_raw(command)
        if r.get("missing"):
            return PLINK_HINT
        return r["stdout"] or r["stderr"] or "(no output)"

    def _preflight(self) -> dict:
        who = f"{self.current_user}@{self.current_ip}"
        fail = lambda msg: {"ok": False, "message": msg}
        probe = tcp_probe(self.current_ip)
        if probe == "refused":
            return fail(f"{self.current_ip} is on, but nothing is listening on SSH port {SSH_PORT}.\n"
                        f"  On that machine run: sudo systemctl enable --now ssh")
        if probe == "no answer":
            return fail(f"no answer from {self.current_ip} on port {SSH_PORT}.\n"
                        f"  1) On the VM run 'hostname -I' - if the IP changed, update it (DHCP can change it).\n"
                        f"  2) Make sure the VM is running, not paused.\n"
                        f"  3) Admin PowerShell: Restart-Service VMnetDHCP; Restart-Service \"VMware NAT Service\"")
        r = self._ssh_raw("hostname && sudo -S -p '' true && echo SUDO_OK", timeout=PREFLIGHT_TIMEOUT)
        if r.get("missing"):
            return fail(PLINK_HINT)
        out, err = r["stdout"], r["stderr"]
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        hosts = [l for l in lines if l != "SUDO_OK" and re.fullmatch(r"[\w.-]+", l)]
        if hosts:
            return {"ok": True, "hostname": hosts[0], "sudo_ok": "SUDO_OK" in lines}
        blob = f"{out}\n{err}".lower()
        if "no password" in blob:
            return fail("no password was entered.")
        if "host key" in blob:
            return fail(f"first connection to {self.current_ip}: its SSH host key isn't trusted yet.\n"
                        f"  Run this once, type y when asked, then press Ctrl+C:\n    plink -ssh {who}\n"
                        f"  Then run the audit again.")
        if any(m in blob for m in ("access denied", "permission denied", "authentication failed")):
            self.memory.forget(self._password_key())
            self._session_pw.pop(self._password_key(), None)
            return fail(f"login to {who} was rejected (wrong password or username).\n"
                        f"  The saved password was cleared — run the audit again to re-enter it.")
        if "timed out" in blob:
            return fail(f"{self.current_ip} answers on port {SSH_PORT}, but the login took over "
                        f"{PREFLIGHT_TIMEOUT}s. The VM may be overloaded - wait a minute and run the audit again.")
        if any(m in blob for m in ("refused", "unreachable", "no route", "network error",
                                   "could not resolve", "name or service")):
            return fail(f"SSH to {who} failed: {(err or out)[:200]}")
        return fail(f"couldn't connect to {who}: {(err or out or 'no response')[:200]}")

    def _open_ssh_window(self) -> str:
        if os.name == "nt":
            ps_cmd = (f'Start-Process powershell -ArgumentList "-NoExit", "-Command", '
                      f'"Write-Host \'Connecting...\' -ForegroundColor Cyan; ssh {self.current_user}@{self.current_ip}"')
            self.mcp.execute_shell(ps_cmd)
            return f"Opened new PowerShell window — SSH to {self.current_user}@{self.current_ip} (this window stays open until you close it)"
        return "Only supported on Windows."

    def _close_note(self) -> str:
        return "\n\n[SSH] Connection closed."


    def run(self, task: str) -> str:
        low = task.lower()
        label, err = self._resolve_target(task)
        if err:
            return err


        if low.startswith("add computer"):
            parsed = self.targets.parse_add_command(task)
            if not parsed:
                return "Could not parse. Use: add computer <ip> as <name> user <username> [for nist|pci|cis|iso 27001|soc 2|hipaa]"
            name, ip, user = parsed
            return self.targets.add(name, ip, user, detect_framework(task))
        elif "list computer" in low or "list target" in low:
            return self.targets.list_str()
        elif "remove computer" in low:
            m = re.search(r'remove computer ([\w-]+)', low)
            return self.targets.remove(m.group(1)) if m else "Specify a name: remove computer <name>"
        elif "scan all computer" in low or "scan all target" in low:
            return self._scan_all()


        if any(k in low for k in ["open vm", "connect to vm", "open ubuntu", "connect ubuntu", "open ssh", "connect to computer"]):
            return self._open_ssh_window()
        if re.search(r"\bports?\b|\bexposed\b|\bexposure\b", low):
            return self._port_scan()
        if re.search(r"\baudit\b|\bscan\b|vulnerab|is my vm (safe|secure)|how (safe|secure)", low):
            return self._audit(task)
        if "firewall" in low or "ufw" in low:
            return self._firewall_check()
        if re.search(r"login|auth|intrusion|failed|brute|attack|hack|threat", low):
            return self._auth_analysis()
        if re.search(r"\bfix\b|remediate|harden|\bsecure\b", low):
            return self._remediate(task)
        if re.search(r"\busers?\b|\baccounts?\b|\bsudo\b|\bwho\b|logged in|logged into", low):
            return self._user_audit()
        if re.search(r"service|process|running", low):
            return self._service_audit()
        if re.search(r"\blogs?\b|activity", low):
            return self._log_analysis()
        if re.search(r"performance|\bcpu\b|memory|\bram\b|disk", low):
            return self._performance_check()
        return self._custom_task(task)


    def _audit(self, task: str) -> str:
        framework = detect_framework(task) or self._default_framework(self.current_ip)
        if re.search(r"\binline\b|\bhere\b|this window", task.lower()):
            return self._full_audit(framework)
        return self._audit_in_new_terminal(framework)

    def _audit_in_new_terminal(self, framework=None) -> str:
        fw_name = FRAMEWORKS[framework]["name"] if framework else None
        if not _is_windows():
            print("  New-terminal mode is Windows-only — running the audit in this window instead.")
            return self._full_audit(framework)

        watcher = Path(__file__).resolve().parent.parent / "audit_watcher.py"
        argv = [sys.executable, str(watcher), "--ip", self.current_ip, "--user", self.current_user]
        if framework:
            argv += ["--framework", framework]
        try:
            subprocess.Popen(argv, cwd=str(watcher.parent),
                             creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010))
        except Exception as e:
            print(f"  Couldn't open a new terminal ({e}) — running the audit here instead.")
            return self._full_audit(framework)
        msg = f"Opened 2 new terminals to audit {self.current_ip} (as {self.current_user})"
        msg += f" for {fw_name}." if fw_name else "."
        msg += ("\n  Terminal 2: the audit itself"
                "\n  Terminal 3: a watcher that monitors it, restarts it if it stalls or crashes, and tells you when it finishes"
                "\nThis window (terminal 1) stays free.")
        if not self.ip_given:
            msg += "\n(No IP given, so this is your primary VM. To audit another computer: security audit 192.168.48.130)"
        return msg

    def _full_audit(self, framework=None) -> str:
        fw = FRAMEWORKS.get(framework) if framework else None
        self._status("starting", "connecting to the computer", fresh=True, framework=framework, started=time.time())
        pre = self._preflight()
        if not pre["ok"]:
            self._status("failed", pre["message"], retryable=False)
            return "Audit stopped — " + pre["message"]
        ip, user, host = self.current_ip, self.current_user, pre["hostname"]
        total = len(AUDIT_COMMANDS)


        self._status("collecting", "reading the computer's CPU and RAM", step=0, total=total)
        compute, tier, guidance = compute_profile(self._ssh(COMPUTE_COMMANDS["cpu_cores"]),
                                                  self._ssh(COMPUTE_COMMANDS["mem_total"]))
        fw_line   = fw["name"] if fw else "General SOC review (add e.g. 'for nist' to frame it)"
        sudo_line = "OK" if pre["sudo_ok"] else "NOT working - firewall and log checks will be incomplete"
        print("\n  " + "=" * 60)
        print("  SECURITY AUDIT")
        print(f"  Target    : {ip}  ({host})  as {user}")
        print(f"  Framework : {fw_line}")
        print(f"  Compute   : {compute}")
        print(f"  sudo      : {sudo_line}")
        print("  " + "=" * 60)

        results = {}
        for i, (name, cmd) in enumerate(AUDIT_COMMANDS.items(), 1):
            label = name.replace("_", " ")
            print(f"  Checking {label}...", end=" ", flush=True)
            self._status("collecting", label, step=i - 1, total=total)
            results[name] = self._ssh(cmd)[:800]
            print("done")
        self._status("collecting", "all checks finished", step=total, total=total)


        self.cache.write(ip, "audit", results)

        evidence  = "\n".join(f"### {k}\n{v[:350]}" for k, v in results.items())
        sudo_note = "" if pre["sudo_ok"] else (
            "\nNOTE: sudo did not work on this host, so firewall status and log checks below may just be error "
            "messages. Report those as 'could not verify' — do not assume they are fine or broken.")
        if fw:
            framing = (f"Frame the report for {fw['name']}. Cite controls ONLY from this list and never invent control IDs:\n"
                       f"{fw['map']}\nFindings table columns: severity | finding | {fw['short']} control | exact fix command.")
        else:
            framing = "Findings table columns: severity | finding | exact fix command."
        prompt = f"""Security audit of {ip} (hostname {host}, user {user}).
Compute profile: {compute}. {guidance}{sudo_note}

{framing}

EVIDENCE:
{evidence}

Write the report:
1. Executive summary (2-3 sentences)
2. Findings table
3. Top 5 fixes, sized for this machine's compute
4. Overall score /10"""

        print("\n  Analyzing with AI...\n")
        self._status("analyzing", "the AI model is writing the report")
        analysis = self.llm(prompt, system=SYSTEM_PROMPT, max_tokens=1000, num_ctx=4096)

        if analysis.startswith(LLM_ERRORS):

            self._status("failed", f"the AI model didn't respond ({analysis[:90]})", retryable=True)
            return ("Audit incomplete — the AI model didn't respond. The data was collected and cached; "
                    "make sure Ollama is running (ollama serve) and run the audit again." + self._close_note())

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path("logs") / f"audit_{ip.replace('.', '_')}_{framework or 'general'}_{stamp}.txt"
        path.parent.mkdir(exist_ok=True)
        path.write_text(f"SECURITY AUDIT - {ip} ({host}) as {user}\nFramework: {fw_line}\nCompute: {compute}\n"
                        f"sudo: {sudo_line}\nGenerated: {stamp}\n\n{evidence}\n\nANALYSIS:\n{analysis}", encoding="utf-8")
        print(f"\n  Report saved: {path}")
        self.memory.log_agent("cybersec", f"audit {ip} {framework or ''}".strip(), analysis[:500])
        self.memory.store("last_audit", stamp)
        scores = re.findall(r"(\d+(?:\.\d+)?)\s*/\s*10", analysis)
        self._status("done", "report saved", report=str(path), score=(scores[-1] + "/10") if scores else None)

        note = (f"\n\nNote: AI-generated gap assessment against {fw['name']} — informational only, not a formal "
                f"audit or certification. Verify control references against the official standard.") if fw else ""
        return analysis + note + self._close_note()

    def _scan_all(self) -> str:

        all_targets, seen = {}, set()
        for name, info in [("primary", {"ip": self.vm_ip, "user": self.vm_user})] + list(self.targets.all().items()):
            if info["ip"] not in seen:
                seen.add(info["ip"])
                all_targets[name] = info
        if len(all_targets) == 1:
            print("  No additional computers registered — scanning primary VM only.")

        summary = []
        for name, info in all_targets.items():
            print(f"\n  === Scanning {name} ({info['ip']}) ===")
            self.current_ip, self.current_user = info["ip"], info["user"]
            result = self._full_audit(info.get("framework") or self._default_framework(info["ip"]))
            summary.append(f"[{name}] {info['ip']}:\n{result[:300]}\n")

        return "MULTI-COMPUTER SCAN COMPLETE\n\n" + "\n".join(summary)

    def _firewall_check(self) -> str:
        print(f"\n  Checking firewall on {self.current_ip}...")
        status = self._ssh(AUDIT_COMMANDS["firewall_status"])
        ports  = self._ssh(AUDIT_COMMANDS["open_ports"])
        self.cache.write(self.current_ip, "firewall", {"status": status, "ports": ports})
        prompt = f"""Firewall analysis for {self.current_ip}:
UFW STATUS: {status}
OPEN PORTS: {ports}
1. Is firewall active? 2. Which ports are risky? 3. Exact UFW fix commands. 4. Install fail2ban?"""
        result = self.llm(prompt, system=SYSTEM_PROMPT, max_tokens=700)
        if self.safe_input("\n  Auto-enable firewall and apply basic rules? [y/n]: ") == "y":
            return self._apply_firewall_hardening()
        return result + self._close_note()

    def _port_scan(self) -> str:
        print(f"\n  Scanning ports on {self.current_ip}...")
        ports = self._ssh(AUDIT_COMMANDS["open_ports"])
        self.cache.write(self.current_ip, "ports", ports)
        prompt = f"Port analysis for {self.current_ip}:\n{ports}\nFor each port: service, risk level, action. Table format."
        return self.llm(prompt, system=SYSTEM_PROMPT, max_tokens=600) + self._close_note()

    def _auth_analysis(self) -> str:
        print(f"\n  Analyzing auth logs on {self.current_ip}...")
        failed  = self._ssh(AUDIT_COMMANDS["failed_logins"])
        success = self._ssh(AUDIT_COMMANDS["successful_logins"])
        sudo    = self._ssh(AUDIT_COMMANDS["sudo_attempts"])
        self.cache.write(self.current_ip, "auth", {"failed": failed, "success": success, "sudo": sudo})
        prompt = f"""Auth analysis for {self.current_ip}:
FAILED: {failed or 'None'}
SUCCESS: {success or 'None'}
SUDO: {sudo or 'None'}
Detect brute force, suspicious activity. Give risk level."""
        return self.llm(prompt, system=SYSTEM_PROMPT, max_tokens=700) + self._close_note()

    def _user_audit(self) -> str:
        print(f"\n  Auditing users on {self.current_ip}...")
        users = self._ssh(AUDIT_COMMANDS["user_accounts"])
        sudo  = self._ssh(AUDIT_COMMANDS["sudo_users"])
        self.cache.write(self.current_ip, "users", {"accounts": users, "sudo": sudo})
        prompt = f"User audit for {self.current_ip}:\nACCOUNTS: {users}\nSUDO: {sudo}\nFlag risks."
        return self.llm(prompt, system=SYSTEM_PROMPT, max_tokens=600) + self._close_note()

    def _service_audit(self) -> str:
        print(f"\n  Auditing services on {self.current_ip}...")
        services = self._ssh(AUDIT_COMMANDS["running_services"])
        self.cache.write(self.current_ip, "services", services)
        prompt = f"Service audit for {self.current_ip}:\n{services[:800]}\nFlag unnecessary/risky services."
        return self.llm(prompt, system=SYSTEM_PROMPT, max_tokens=600) + self._close_note()

    def _log_analysis(self) -> str:
        print(f"\n  Analyzing logs on {self.current_ip}...")
        auth = self._ssh("sudo tail -50 /var/log/auth.log")
        self.cache.write(self.current_ip, "logs", auth)
        prompt = f"Log analysis for {self.current_ip}:\n{auth}\nIdentify incidents, anomalies, actions needed."
        return self.llm(prompt, system=SYSTEM_PROMPT, max_tokens=700) + self._close_note()

    def _performance_check(self) -> str:
        print(f"\n  Checking performance on {self.current_ip}...")
        cpu  = self._ssh(AUDIT_COMMANDS["cpu_usage"])
        mem  = self._ssh(AUDIT_COMMANDS["memory_usage"])
        disk = self._ssh(AUDIT_COMMANDS["disk_usage"])
        self.cache.write(self.current_ip, "performance", {"cpu": cpu, "mem": mem, "disk": disk})
        prompt = f"Performance for {self.current_ip}:\nCPU: {cpu}\nMEM: {mem}\nDISK: {disk}\nSummarize, flag issues."
        return self.llm(prompt, system=SYSTEM_PROMPT, max_tokens=500) + self._close_note()

    def _apply_firewall_hardening(self) -> str:
        print(f"\n  Applying firewall hardening to {self.current_ip}...")
        steps = [
            ("Setting default deny incoming", REMEDIATION["default_deny"]),
            ("Allowing SSH (port 22)",        REMEDIATION["allow_ssh"]),
            ("Enabling UFW firewall",         REMEDIATION["enable_firewall"]),
        ]
        results = []
        for desc, cmd in steps:
            print(f"  {desc}...", end=" ", flush=True)
            out = self._ssh(cmd)
            status = "OK" if "error" not in out.lower() else "FAIL"
            print(status)
            results.append(f"[{status}] {desc}")
        verify = self._ssh(AUDIT_COMMANDS["firewall_status"])
        self.memory.log_agent("cybersec", "firewall_hardening", "\n".join(results))
        return "Firewall Hardening Applied:\n\n" + "\n".join(results) + f"\n\nNew Status:\n{verify}" + self._close_note()

    def _custom_task(self, task: str) -> str:
        prompt = f"Generate a single bash command for a Linux VM to: {task}\nOutput ONLY the command."
        cmd = self.llm(prompt, system=SYSTEM_PROMPT, max_tokens=80).strip().strip("`")
        print(f"\n  Command: {cmd}")
        if self.safe_input("  Run on VM? [y/n]: ") == "y":
            output = self._ssh(cmd)
            interp = self.llm(f"Command: {cmd}\nOutput: {output}\nExplain briefly.", system=SYSTEM_PROMPT, max_tokens=200)
            return f"Output:\n{output}\n\nInterpretation:\n{interp}" + self._close_note()
        return f"Command ready: {cmd}"

    def _remediate(self, task: str) -> str:
        plan = self.llm(
            f"Remediation plan for: {task}\nVM: {self.current_ip}\nProvide step-by-step fix with exact bash commands.",
            system=SYSTEM_PROMPT, max_tokens=700)
        print(f"\n{plan}")
        if self.safe_input("\n  Auto-apply firewall hardening? [y/n]: ") == "y":
            return self._apply_firewall_hardening()
        return plan
