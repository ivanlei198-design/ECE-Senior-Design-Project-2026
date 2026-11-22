from agents.base_agent import BaseAgent

class PlannerAgent(BaseAgent):
    SYSTEM_PROMPT = "You are a senior AI systems architect. Break tasks into clear numbered steps labeled [CODE],[BROWSE],[ANALYZE],[SHELL],[THINK]. Be concise and direct."

    def run(self, task: str) -> str:
        name = self.memory.recall("user_name")
        ctx = f"User: {name}. " if name else ""
        return self.llm(f"{ctx}Create a detailed action plan for: {task}", system=self.SYSTEM_PROMPT, max_tokens=800)
