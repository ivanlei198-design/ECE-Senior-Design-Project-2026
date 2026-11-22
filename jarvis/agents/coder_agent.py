import time
from pathlib import Path
from agents.base_agent import BaseAgent

MAX_HEAL = 3

class CoderAgent(BaseAgent):
    SYSTEM_PROMPT = "You are an expert software engineer. Output ONLY code in ```python or ```powershell blocks. Include error handling and comments."

    def run(self, task: str) -> str:
        lang = "powershell" if any(k in task.lower() for k in ["powershell", ".ps1"]) else "python"
        response = self.llm(task, system=self.SYSTEM_PROMPT, max_tokens=1200)
        code = self._extract_code(response, lang)
        if not code:
            return response
        ext = "ps1" if lang == "powershell" else "py"
        p = Path(f"generated_code/agent_{int(time.time())}.{ext}")
        p.parent.mkdir(exist_ok=True)
        p.write_text(code)
        self.memory.save_code(p.name, code, lang)
        print(f"\n  Code saved: {p}")
        if self.safe_input("\n  Execute? [y/n]: ") == "y":
            return self._run_heal(code, lang, task, p)
        return f"Code saved to {p}"

    def _run_heal(self, code, lang, task, fp, attempt=1):
        cmd = f'python "{fp}"' if lang == "python" else f'powershell -ExecutionPolicy Bypass -File "{fp}"'
        r = self.mcp.execute_shell(cmd)
        if r["success"]:
            self.memory.log_agent("coder", task, r["stdout"])
            return f"Success:\n{r['stdout']}"
        if attempt >= MAX_HEAL:
            return f"Failed after {MAX_HEAL} attempts:\n{r['stderr']}"
        print(f"\n  Self-healing attempt {attempt + 1}...")
        fix = self.llm(f"ERROR: {r['stderr'][:400]}\nCODE: {code[:800]}\nFix it.", system=self.SYSTEM_PROMPT, max_tokens=1000)
        fixed = self._extract_code(fix, lang)
        if fixed and fixed != code:
            fp.write_text(fixed)
            return self._run_heal(fixed, lang, task, fp, attempt + 1)
        return f"Could not fix: {r['stderr']}"
