import subprocess, platform, json

class ToolRegistry:
    def get_gpu_info(self):
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu", "--format=csv,noheader"], capture_output=True, text=True, timeout=10)
            return r.stdout.strip() or "No NVIDIA GPU"
        except Exception:
            return "nvidia-smi not available"

    def get_sysinfo(self):
        return json.dumps({"os": platform.system(), "cpu": platform.processor()[:60], "python": platform.python_version()}, indent=2)

    def list_ollama_models(self):
        try:
            r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
            return r.stdout or "No models"
        except Exception:
            return "Ollama not installed"
