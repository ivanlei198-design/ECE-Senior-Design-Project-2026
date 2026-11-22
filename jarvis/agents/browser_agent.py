import re
from agents.base_agent import BaseAgent

class BrowserAgent(BaseAgent):
    SYSTEM_PROMPT = "You are a web automation expert. Generate Playwright Python scripts for browser tasks."

    def run(self, task: str) -> str:
        url = re.search(r'https?://[^\s]+', task)
        if url:
            self.mcp.browser_navigate(url.group(0))
            return f"Opened: {url.group(0)}"
        domain = re.search(r'\b([a-zA-Z0-9-]+\.(com|org|net|io|gov|edu))\b', task)
        if domain:
            self.mcp.browser_navigate("https://" + domain.group(0))
            return f"Opened: {domain.group(0)}"
        return self.llm(task, system=self.SYSTEM_PROMPT, max_tokens=600)
