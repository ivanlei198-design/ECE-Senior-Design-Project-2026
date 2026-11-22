import re
from agents.base_agent import BaseAgent

class SelfHealingAgent(BaseAgent):
    SYSTEM_PROMPT = "You are an expert debugger. Diagnose errors, provide exact fixes. If a pip install is needed, include the command."

    def run(self, task: str) -> str:
        response = self.llm(f"Fix this error:\n{task}", system=self.SYSTEM_PROMPT, max_tokens=500)
        pip_match = re.search(r'pip install ([\w\-]+)', response)
        if pip_match:
            pkg = pip_match.group(1)
            if self.safe_input(f"\n  Auto-install '{pkg}'? [y/n]: ") == "y":
                r = self.mcp.execute_shell(f"pip install {pkg}")
                response += f"\n\n{'Installed' if r['success'] else 'Failed to install'} {pkg}"
        self.memory.log_agent("healer", task[:200], response[:500])
        return response
