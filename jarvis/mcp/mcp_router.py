import subprocess, os, re, threading, webbrowser
from pathlib import Path
from datetime import datetime

class MCPRouter:
    def __init__(self):
        self._queue = []
        self._lock = threading.Lock()

    def execute_shell(self, command, shell_type="auto", timeout=30):
        if shell_type == "auto":
            shell_type = "powershell" if os.name == "nt" else "bash"
        try:
            cmd = ["powershell", "-NoProfile", "-Command", command] if shell_type == "powershell" else ["bash", "-c", command]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return {"stdout": r.stdout.strip(), "stderr": r.stderr.strip(), "returncode": r.returncode, "success": r.returncode == 0}
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": "Command timed out", "returncode": -1, "success": False}
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "returncode": -1, "success": False}

    def run_argv(self, args, input_text=None, timeout=30):
        try:
            r = subprocess.run(args, input=input_text, capture_output=True, text=True, timeout=timeout)
            return {"stdout": r.stdout.strip(), "stderr": r.stderr.strip(), "returncode": r.returncode,
                    "success": r.returncode == 0, "missing": False}
        except FileNotFoundError:
            return {"stdout": "", "stderr": f"{args[0]} not found", "returncode": -1, "success": False, "missing": True}
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": "Command timed out", "returncode": -1, "success": False, "missing": False}
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "returncode": -1, "success": False, "missing": False}

    def ssh_exec(self, ip, user, password, command, timeout=25):
        sudo_re = r"(^|[|&;(]\s*)sudo\s+"
        n_sudo = len(re.findall(sudo_re, command))
        remote = re.sub(sudo_re, r"\1sudo -S -p '' ", command) if n_sudo else command
        if os.name == "nt":
            args = ["plink", "-ssh", f"{user}@{ip}", "-pw", password, "-batch", remote]
        else:
            args = ["sshpass", "-p", password, "ssh", "-o", "StrictHostKeyChecking=no",
                    "-o", "ConnectTimeout=10", f"{user}@{ip}", remote]
        return self.run_argv(args, input_text=(password + "\n") * n_sudo if n_sudo else None, timeout=timeout)

    def browser_navigate(self, url):
        try:
            webbrowser.open(url)
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def write_file(self, path, content):
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(content, encoding="utf-8")
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def read_file(self, path):
        try:
            return {"success": True, "content": Path(path).read_text(encoding="utf-8")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def ping(self, host):
        cmd = f"ping -n 1 {host}" if os.name == "nt" else f"ping -c 1 {host}"
        return self.execute_shell(cmd)["success"]

    def send_message(self, from_agent, to_agent, payload):
        with self._lock:
            self._queue.append({"from": from_agent, "to": to_agent, "payload": payload, "ts": datetime.now().isoformat()})

    def receive_messages(self, agent_name):
        with self._lock:
            msgs = [m for m in self._queue if m["to"] == agent_name]
            self._queue = [m for m in self._queue if m["to"] != agent_name]
            return msgs
