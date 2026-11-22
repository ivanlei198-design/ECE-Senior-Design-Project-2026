from pathlib import Path
from agents.base_agent import BaseAgent
from tools.cache_manager import CacheManager

class AnalystAgent(BaseAgent):
    SYSTEM_PROMPT = "You are a senior data analyst. Write complete Python code using pandas and matplotlib. Save charts with plt.savefig(). Output ONLY code in ```python blocks."

    def __init__(self, memory, mcp):
        super().__init__(memory, mcp)
        self.cache = CacheManager()

    def run(self, task: str) -> str:
        low = task.lower()
        if "cache" in low or "cached" in low:
            return self._analyze_cache(task)


        found = [str(f) for d in ("logs", "data", ".") for f in Path(d).glob("*.csv")]
        hint = f"\nAvailable local data files: {', '.join(found)}" if found else \
               "\nNo local data files found — generate realistic sample data that matches the request exactly."
        response = self.llm(task + hint, system=self.SYSTEM_PROMPT, max_tokens=1200)
        code = self._extract_code(response, "python")
        if not code:
            return response
        if self.safe_input("\n  Run analysis? [y/n]: ") == "y":
            p = Path("generated_code/analysis.py")
            p.parent.mkdir(exist_ok=True)
            p.write_text(code)
            r = self.mcp.execute_shell(f'python "{p}"')
            return f"{'Done' if r['success'] else 'Error'}:\n{r['stdout'] or r['stderr']}"
        return "Code generated. Not executed."

    def _analyze_cache(self, task: str) -> str:
        targets = self.cache.list_targets()
        if not targets:
            return "No cached data yet. Run a security audit or monitor cycle first."
        prompt = f"""The user has locally cached data from these targets: {', '.join(targets)}
Task: {task}
Summarize what local cached analysis is possible and what's available, in 3-4 sentences."""
        return self.llm(prompt, system=self.SYSTEM_PROMPT, max_tokens=300)
