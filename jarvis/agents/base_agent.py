import requests, json, time, threading
from memory.persistent_memory import PersistentMemory
from mcp.mcp_router import MCPRouter


_capture = threading.local()

def begin_capture():
    _capture.chunks = []

def end_capture():
    chunks = getattr(_capture, "chunks", None) or []
    _capture.chunks = None
    return chunks

def strip_streamed(response, chunks):
    out = response or ""
    for c in chunks:
        if c and c in out:
            out = out.replace(c, "" if out.strip().startswith(c) else "(shown above)", 1)
    return out.strip()

def run_captured(fn, *args, **kwargs):
    begin_capture()
    try:
        value = fn(*args, **kwargs)
    finally:
        chunks = end_capture()
    full = "" if value is None else str(value)
    return full, strip_streamed(full, chunks)


OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3"

class BaseAgent:
    SYSTEM_PROMPT = "You are a helpful AI agent. Be concise and accurate."
    progress_hook = None

    def __init__(self, memory: PersistentMemory, mcp: MCPRouter):
        self.memory = memory
        self.mcp = mcp

    def llm(self, prompt: str, system: str = None, max_tokens: int = 800, use_context: bool = False, num_ctx: int = 2048) -> str:
        system = system or self.SYSTEM_PROMPT


        context = self.memory.get_conversation_context(n=2) if use_context else ""
        full_prompt = f"{context}\n\nCurrent request: {prompt}" if context else prompt
        payload = {
            "model": MODEL, "prompt": full_prompt, "system": system, "stream": True,
            "options": {"num_predict": max_tokens, "temperature": 0.7, "num_ctx": num_ctx}
        }
        try:
            response = requests.post(OLLAMA_URL, json=payload, stream=True, timeout=60)
            full = ""
            last_token_time = time.time()
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line)
                    token = chunk.get("response", "")
                    print(token, end="", flush=True)
                    full += token
                    last_token_time = time.time()
                    if BaseAgent.progress_hook:
                        try:
                            BaseAgent.progress_hook()
                        except Exception:
                            pass
                    if chunk.get("done"):
                        break
                if time.time() - last_token_time > 30:
                    print("\n  [TIMEOUT] No response for 30s.")
                    break
            print()
            text = full.strip()
            if text and getattr(_capture, "chunks", None) is not None:
                _capture.chunks.append(text)
            return text if text else "No response. Try again."
        except requests.exceptions.ConnectionError:
            return "Cannot connect to Ollama. Run: ollama serve"
        except requests.exceptions.Timeout:
            return "Ollama timed out. Try: taskkill /F /IM ollama.exe then relaunch."
        except Exception as e:
            return f"LLM error: {e}"

    def safe_input(self, prompt: str, default: str = "n") -> str:
        try:
            return input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(f"\n  Input cancelled, defaulting to '{default}'")
            return default
        except Exception:
            return default

    def run(self, task: str) -> str:
        return self.llm(task)

    def _extract_code(self, text: str, lang: str = "python"):
        import re
        match = re.search(rf"```{lang}?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else None
