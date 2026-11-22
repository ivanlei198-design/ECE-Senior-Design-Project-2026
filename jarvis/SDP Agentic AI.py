
import os
import re
import threading
import time
from datetime import datetime
from memory.persistent_memory import PersistentMemory
from agents.planner_agent import PlannerAgent
from agents.coder_agent import CoderAgent
from agents.browser_agent import BrowserAgent
from agents.analyst_agent import AnalystAgent
from agents.healer_agent import SelfHealingAgent
from agents.cybersec_agent import CyberSecAgent, find_ip
from agents.monitor_agent import MonitorAgent
from agents.gpu_agent import GPUAgent
from agents.base_agent import run_captured
from tools.status_board import AGENT_HEARTBEAT, write_status
from mcp.mcp_router import MCPRouter
from tools.tool_registry import ToolRegistry

TASK_TIMEOUT = 150


class C:
    RESET="\033[0m"; BOLD="\033[1m"; CYAN="\033[96m"; GREEN="\033[92m"
    YELLOW="\033[93m"; RED="\033[91m"; MAGENTA="\033[95m"; DIM="\033[2m"; WHITE="\033[97m"


BANNER = f"""
{C.CYAN}{C.BOLD}
   ╔══════════════════════════════════════════════════════════════════════════╗
   ║                                                                          ║
   ║   █████╗  ██████╗ ███████╗███╗   ██╗████████╗██╗ ██████╗    █████╗ ██╗   ║
   ║  ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝██║██╔════╝   ██╔══██╗██║   ║
   ║  ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   ██║██║        ███████║██║   ║
   ║  ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   ██║██║        ██╔══██║██║   ║
   ║  ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   ██║╚██████╗   ██║  ██║██║   ║
   ║  ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚═╝ ╚═════╝   ╚═╝  ╚═╝╚═╝   ║
   ║                                                                          ║
   ║                S E N I O R   D E S I G N   P R O J E C T                 ║
   ║                                                                          ║
   ║            Local Multi-Agent AI System  |  Ollama + Llama3 8B            ║
   ║               100% Free  |  No Cloud  |  Persistent Memory               ║
   ║              Autonomous Tool Use  |  Hardware Adaptability               ║
   ║                                                                          ║
   ╚══════════════════════════════════════════════════════════════════════════╝
{C.RESET}"""


INTENT_MAP = {
    "monitor":  ["start monitor", "stop monitor", "monitor status", "monitor the vm",
                 "continuous monitor", "background monitor", "latest report",
                 "last report", "show report", "is monitor"],
    "code":     ["write a script", "write a python", "write code", "generate code",
                 "create a script", "implement", "debug", "fix my code", "write a function",
                 "write a powershell", "python script", "powershell script", "bash script",
                 "generate a script", "generate a python", "generate a program",
                 "make a script", "make a program", "write a program", "write a tool",
                 "script that", "program that", "code that", "code to"],
    "browse":   ["open ", "browse", "navigate to", "go to website", "search the web"],
    "analyze":  ["analyze", "analysis", "csv", "chart", "plot", "statistics", "graph", "visualize"],
    "plan":     ["plan", "design", "architect", "roadmap", "strategy", "outline",
                 "how would i build", "what are the steps"],
}

GENERAL_QA_STARTS = [
    "what is", "what are", "what does", "what do", "what can",
    "explain", "tell me", "describe", "define", "summarize",
    "how does", "how do", "how can", "why is", "why does", "why are",
    "who is", "who are", "who made", "who created",
    "are you", "can you", "is there", "where is", "when did",
    "tell me a", "give me a", "what time", "what day",
]

GPU_WORDS = ("graph", "plot", "chart", "visuali", "stats", "usage",
             "performance", "temperature", "utilization")

VM_WORDS  = ("my vm", "the vm", "my ubuntu", "my server", "this vm")
VM_TOPICS = ("logged", "safe", "secure", "exposed", "attack", "hack", "ports", "firewall", "users",
             "running", "cpu", "memory", "disk", "performance", "vulnerab", "threat", "intrusion",
             "audit", "scan")

CYBERSEC_ACTIONS = [
    "check firewall", "check ufw", "check port", "check auth",
    "check log", "check user", "check service", "check vm",
    "check running", "check the vm", "check my vm", "check performance", "check cpu",
    "check memory", "check disk", "check connection",
    "scan open", "scan port", "scan my", "scan the vm", "scan all computer", "scan all target",
    "security audit", "full audit", "run audit", "audit my vm", "audit the vm",
    "harden the vm", "harden my vm", "secure the vm", "secure my vm",
    "enable firewall", "enable ufw", "fix the vm", "fix firewall",
    "open vm", "connect to vm", "open ubuntu", "connect ubuntu", "open ssh", "connect to computer",
    "failed login", "login attempt", "show firewall", "show ports",
    "list ports", "list users on", "check for brute",
    "add computer", "list computer", "list target", "remove computer",
]


AGENT_ROLES = {
    "cybersec": "security audits and checks over SSH",
    "monitor":  "continuous monitoring and threat reports",
    "gpu":      "GPU performance graphs",
    "planner":  "breaks tasks into steps",
    "coder":    "writes and fixes code",
    "browser":  "opens and reads web pages",
    "analyst":  "analyzes data and makes charts",
    "healer":   "diagnoses and fixes errors",
}


class Orchestrator:
    def __init__(self):
        print(BANNER)
        print(f"{C.YELLOW}[BOOT]{C.RESET} Initializing subsystems...\n")
        self.memory  = PersistentMemory()
        self.tools   = ToolRegistry()
        self.mcp     = MCPRouter()
        self.monitor = MonitorAgent(self.memory, self.mcp)
        self.agents  = {
            "cybersec": CyberSecAgent(self.memory, self.mcp),
            "monitor":  self.monitor,
            "gpu":      GPUAgent(self.memory, self.mcp),
            "planner":  PlannerAgent(self.memory, self.mcp),
            "coder":    CoderAgent(self.memory, self.mcp),
            "browser":  BrowserAgent(self.memory, self.mcp),
            "analyst":  AnalystAgent(self.memory, self.mcp),
            "healer":   SelfHealingAgent(self.memory, self.mcp),
        }
        self._check_ollama()
        print(f"\n{C.GREEN}[AGENT ONLINE]{C.RESET} All systems ready. Type {C.CYAN}'help'{C.RESET} for commands.\n")

    def _check_ollama(self):
        import subprocess
        print(f"{C.DIM}  Checking Ollama...{C.RESET}", end=" ", flush=True)
        try:
            r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
            if "llama3" in r.stdout:
                print(f"{C.GREEN}OK - llama3 ready{C.RESET}")
            else:
                print(f"{C.YELLOW}WARNING - llama3 not found. Run: ollama pull llama3{C.RESET}")
        except Exception as e:
            print(f"{C.RED}ERROR - {e}{C.RESET}")

    def _detect_intent(self, user_input: str) -> str:
        low = user_input.lower()


        if any(w in low for w in VM_WORDS) and any(t in low for t in VM_TOPICS):
            return "cybersec"
        if low.startswith("audit") or re.search(r"\b(run|start|do|perform|begin)\b.*\baudit\b", low):
            return "cybersec"

        for qa in GENERAL_QA_STARTS:
            if low.startswith(qa):
                return "general"

        if "gpu" in low and any(w in low for w in GPU_WORDS):
            return "gpu"

        for trigger in INTENT_MAP["monitor"]:
            if trigger in low:
                return "monitor"

        if re.search(r"\baudit\b", low):
            return "cybersec"

        for trigger in CYBERSEC_ACTIONS:
            if trigger in low:
                return "cybersec"

        scores = {k: sum(1 for kw in v if kw in low)
                  for k, v in INTENT_MAP.items() if k not in ("monitor",)}
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "general"

    def _route(self, user_input: str, intent: str) -> str:
        if intent == "general":
            return self.agents["planner"].llm(
                user_input,
                system="You are a helpful AI assistant. Answer directly and concisely. Do not create plans or numbered steps unless specifically asked.",
                max_tokens=400,
                use_context=True
            )
        agent_map = {
            "cybersec": "cybersec", "monitor": "monitor", "gpu": "gpu", "code": "coder",
            "browse": "browser", "analyze": "analyst", "plan": "planner",
        }
        key = agent_map.get(intent, "planner")
        print(f"{C.DIM}  Routing to {C.MAGENTA}{key.upper()} AGENT{C.RESET}")
        return self.agents[key].run(user_input)


    def _route_with_timeout(self, user_input: str, intent: str):
        result = {"value": ("", ""), "done": False, "error": None}

        def worker():
            try:
                result["value"] = run_captured(self._route, user_input, intent)
            except Exception as e:
                result["error"] = e
            finally:
                result["done"] = True

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(timeout=TASK_TIMEOUT)

        if not result["done"]:
            print(f"\n{C.YELLOW}  [TIMEOUT] Task exceeded {TASK_TIMEOUT}s — returning to prompt.{C.RESET}")
            print(f"{C.DIM}  (It may still finish in the background and print output later.){C.RESET}")
            return "", ""
        if result["error"]:
            raise result["error"]
        return result["value"]

    def _heartbeat(self):
        while True:
            write_status(AGENT_HEARTBEAT, heartbeat=time.time(), pid=os.getpid(), closed=False)
            time.sleep(5)

    def _memory_command(self, text: str):
        t = text.strip().rstrip(".!")
        low = t.lower().rstrip("?")
        m = re.match(r"set vm\s+(\S+)(?:\s+user(?:name)?\s+(\S+))?$", t, re.IGNORECASE)
        if m:
            ip, valid = find_ip(m.group(1))
            if not ip or not valid:
                return "That isn't a valid IP address. Example: set vm 192.168.1.50 user myname"
            user = m.group(2) or self.memory.recall("vm_user") or "ivansdp"
            self.memory.store("vm_ip", ip)
            self.memory.store("vm_user", user)
            cyber = self.agents["cybersec"]
            for a in (cyber, self.monitor):
                a.vm_ip, a.vm_user = ip, user
            cyber.current_ip, cyber.current_user = ip, user
            return (f"Primary computer set to {user}@{ip}. "
                    f"If a monitor is running, type 'stop monitor' and start it again to use the new address.")
        if low in ("show vm", "which vm"):
            return f"Primary computer: {self.memory.recall('vm_user') or 'ivansdp'}@{self.memory.recall('vm_ip') or '192.168.48.128'}"

        key_of = lambda words: "my_" + re.sub(r"\W+", "_", words.strip().lower()).strip("_")

        m = re.match(r"remember (?:that )?my (.+?) (?:is|are) (.+)", t, re.IGNORECASE)
        if m:
            self.memory.store(key_of(m.group(1)), m.group(2).strip())
            return f"Saved: my {m.group(1).strip()} = {m.group(2).strip()}"
        m = re.match(r"remember (?:that )?(.+)", t, re.IGNORECASE)
        if m:
            n = len(self.memory.recall_prefix("note_")) + 1
            self.memory.store(f"note_{n}", m.group(1).strip())
            return f"Saved note {n}: {m.group(1).strip()}"

        m = re.match(r"what(?:'s| is) my (.+)", low)
        if m:
            what = m.group(1).strip()
            if "password" in what:
                return "I keep saved passwords hidden."
            val = self.memory.recall("user_name") if what == "name" else self.memory.recall(key_of(what))
            if val:
                return f"Your {what} is {val}."
            if what == "name":
                return "I don't know your name yet. Tell me: my name is <name>"
            return None

        if re.match(r"what do you (remember|know) about me|what have i told you", low):
            facts = {k: v for k, v in self.memory.recall_all().items()
                     if k == "user_name" or k.startswith(("my_", "note_"))}
            if not facts:
                return "Nothing saved yet. Try: remember my gpu is rtx 3070"
            return "Saved so far:\n" + "\n".join(
                f"  {k}: {'********' if 'password' in k else v}" for k, v in facts.items())
        return None

    def _help(self):
        print(f"\n{C.CYAN}{'─'*62}{C.RESET}")
        sections = [
            ("CYBERSECURITY (Primary VM: 192.168.48.128)", [
                ("security audit",       "Full VM scan + AI report"),
                ("check firewall",       "UFW status + port analysis"),
                ("scan open ports",      "All open ports + risk levels"),
                ("check auth logs",      "Brute force + login attempts"),
                ("check users",          "User accounts + sudo access"),
                ("check performance",    "CPU, RAM, disk, connections"),
                ("harden the vm",        "Auto-apply firewall rules"),
                ("open vm",              "Open SSH session in new window"),
            ]),
            ("SECURITY AUDIT OPTIONS (New)", [
                ("security audit",                          "Audit in a NEW terminal + a 3rd terminal that watches it"),
                ("security audit 192.168.48.130",           "Audit a specific IP address"),
                ("security audit for nist",                 "Frame the report for a framework"),
                ("audit 192.168.48.130 for pci user admin", "IP + framework + SSH user"),
                ("security audit inline",                   "Run it in this window instead"),
                ("  frameworks: cis, nist, iso 27001, soc 2, pci dss, hipaa", ""),
            ]),
            ("MULTI-COMPUTER (New)", [
                ("add computer <ip> as <name> user <user> for pci", "Register a machine + its default framework"),
                ("list computers",       "Show registered machines"),
                ("scan all computers",   "Audit every registered machine"),
                ("remove computer <name>", "Unregister a machine"),
            ]),
            ("GPU PERFORMANCE GRAPHS (New)", [
                ("graph gpu performance",              "30s of real GPU stats under llama3 load"),
                ("graph gpu performance for 60 seconds", "Choose the duration (10-90s)"),
                ("graph gpu performance idle",         "Baseline with no load"),
            ]),
            ("CONTINUOUS MONITORING (SOC Mode)", [
                ("start monitor",        "Background poll every 60s"),
                ("stop monitor",         "Stop background monitoring"),
                ("monitor status",       "Show poll history + threats"),
                ("show latest report",   "Show last AI security report"),
            ]),
            ("OTHER AGENTS", [
                ("write a python script...", "Coder Agent + self-healing"),
                ("analyze data.csv",         "Analyst Agent + charts"),
                ("plan a system...",         "Planner Agent"),
                ("open github.com",          "Browser Agent"),
                ("remember my gpu is rtx 3070", "Save a fact (kept after restart)"),
                ("what is my gpu",            "Recall it"),
                ("what do you remember about me", "List everything you saved"),
                ("set vm 192.168.1.50 user myname", "Choose your own Ubuntu computer (saved)"),
                ("show vm",                  "Show which computer is the primary one"),
                ("memory",                   "Show all stored memory (passwords hidden)"),
                ("exit",                     "Quit"),
            ]),
        ]
        for section, cmds in sections:
            print(f"\n  {C.YELLOW}{section}{C.RESET}")
            for cmd, desc in cmds:
                print(f"    {C.CYAN}{cmd:<42}{C.RESET}{C.DIM}{desc}{C.RESET}")
        print(f"\n{C.CYAN}{'─'*62}{C.RESET}\n")

    def run(self):
        self.memory.store("session_start", datetime.now().strftime("%Y%m%d_%H%M%S"))
        threading.Thread(target=self._heartbeat, daemon=True).start()

        while True:
            try:
                user_input = input(f"\n{C.BOLD}{C.WHITE}You{C.RESET} > ").strip()
                if not user_input:
                    continue
                low = user_input.lower()

                if low in ("exit", "quit", "q"):
                    write_status(AGENT_HEARTBEAT, heartbeat=time.time(), pid=os.getpid(), closed=True)
                    print(f"\n{C.CYAN}[AGENT]{C.RESET} Goodbye. Session saved.\n")
                    break
                elif low == "help":
                    self._help()
                    continue
                elif low == "clear":
                    os.system("cls" if os.name == "nt" else "clear")
                    print(BANNER)
                    continue
                elif low == "agents":
                    for n, a in self.agents.items():
                        print(f"  {C.MAGENTA}{n.upper():<12}{C.RESET} {AGENT_ROLES.get(n, '')}")
                    continue
                elif low == "memory":
                    facts = self.memory.recall_all()
                    print("\n".join(f"  {k}: {'********' if 'password' in k.lower() else v}" for k, v in facts.items()) if facts else "No memories.")
                    continue

                if "my name is" in low:
                    name = user_input.split("my name is")[-1].strip().split()[0]
                    self.memory.store("user_name", name)
                    print(f"{C.GREEN}[MEMORY]{C.RESET} Stored: name = {name}")

                mem_reply = self._memory_command(user_input)
                if mem_reply is not None:
                    print(f"\n{C.CYAN}[AGENT]{C.RESET} {mem_reply}")
                    if "password" not in low:
                        self.memory.log_conversation(user_input, mem_reply)
                    print(f"\n{C.DIM}  Ready for next command.{C.RESET}")
                    continue

                intent = self._detect_intent(user_input)
                print(f"\n{C.CYAN}[AGENT]{C.RESET} ", end="", flush=True)

                try:
                    response, shown = self._route_with_timeout(user_input, intent)
                except KeyboardInterrupt:
                    print(f"\n{C.YELLOW}  Task cancelled.{C.RESET}")
                    response = shown = ""
                except EOFError:
                    print(f"\n{C.YELLOW}  Input interrupted. Returning to prompt.{C.RESET}")
                    response = shown = ""
                except Exception as e:
                    try:
                        response, shown = run_captured(self.agents["healer"].run, f"ERROR: {e}\nTASK: {user_input}")
                    except Exception:
                        response = shown = f"{C.RED}[ERROR]{C.RESET} {e}"

                if shown:
                    print(shown)
                self.memory.log_conversation(user_input, response)
                print(f"\n{C.DIM}  Ready for next command.{C.RESET}")

            except KeyboardInterrupt:
                print(f"\n\n{C.CYAN}[AGENT]{C.RESET} Ctrl+C - type 'exit' to quit.\n")
                continue
            except EOFError:
                print(f"\n{C.YELLOW}  Input error. Continuing...{C.RESET}")
                continue
            except Exception as e:
                print(f"{C.RED}[ERROR]{C.RESET} {e} — continuing.")
                continue


if __name__ == "__main__":
    Orchestrator().run()
