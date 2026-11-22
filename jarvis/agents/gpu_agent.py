
import csv
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import requests

from agents.base_agent import BaseAgent, OLLAMA_URL, MODEL

OUT_DIR = Path("logs/gpu_graphs")
DEFAULT_SECONDS = 30
MIN_SECONDS, MAX_SECONDS = 10, 90
QUERY = "utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"
LOAD_PROMPT = "Explain in great detail how multi-agent AI systems work, with several examples."


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _read_gpu():
    try:
        r = subprocess.run(
            ["nvidia-smi", f"--query-gpu={QUERY}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
    except FileNotFoundError:
        raise
    except Exception:
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    parts = [p.strip() for p in r.stdout.strip().splitlines()[0].split(",")]
    if len(parts) < 5:
        return None
    return {"util": _num(parts[0]), "vram": _num(parts[1]), "vram_total": _num(parts[2]),
            "temp": _num(parts[3]), "power": _num(parts[4])}


def _gpu_name():
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip().splitlines()[0] if r.stdout.strip() else "GPU"
    except Exception:
        return "GPU"


def _generate_load(stop: threading.Event, errors: list):
    payload = {"model": MODEL, "prompt": LOAD_PROMPT, "stream": True,
               "options": {"num_predict": 500, "num_ctx": 2048}}
    while not stop.is_set():
        try:
            with requests.post(OLLAMA_URL, json=payload, stream=True, timeout=60) as r:
                for _ in r.iter_lines():
                    if stop.is_set():
                        break
        except Exception as e:
            errors.append(str(e))
            return


class GPUAgent(BaseAgent):

    def run(self, task: str) -> str:
        low = task.lower()
        m = re.search(r'(\d+)\s*(?:s\b|sec)', low)
        seconds = min(max(int(m.group(1)), MIN_SECONDS), MAX_SECONDS) if m else DEFAULT_SECONDS
        idle = "idle" in low or "no load" in low

        try:
            first = _read_gpu()
        except FileNotFoundError:
            return "nvidia-smi not found. This needs an NVIDIA GPU with drivers installed (your RTX 3070 laptop)."
        if first is None:
            return "Could not read GPU stats from nvidia-smi."

        stop, errors = threading.Event(), []
        if not idle:
            print("  Putting the GPU under load with a background llama3 generation (add 'idle' to skip)...")
            threading.Thread(target=_generate_load, args=(stop, errors), daemon=True).start()

        print(f"  Sampling GPU every second for {seconds}s...")
        samples, start = [], time.time()
        try:
            for i in range(seconds):
                t0 = time.time()
                s = _read_gpu()
                if s:
                    s["t"] = round(t0 - start, 1)
                    samples.append(s)
                    if (i + 1) % 5 == 0:
                        print(f"    {i + 1:>3}s  util {s['util']}%  vram {s['vram']} MB  temp {s['temp']}C")
                time.sleep(max(0.0, 1.0 - (time.time() - t0)))
        finally:
            stop.set()

        if len(samples) < 2:
            return "Not enough GPU samples collected to graph."

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path, png_path = OUT_DIR / f"gpu_{stamp}.csv", OUT_DIR / f"gpu_{stamp}.png"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["seconds", "util_pct", "vram_mb", "vram_total_mb", "temp_c", "power_w"])
            for s in samples:
                w.writerow([s["t"], s["util"], s["vram"], s["vram_total"], s["temp"], s["power"]])

        loaded = not idle and not errors
        self._plot(samples, png_path, _gpu_name(), loaded)
        try:
            if os.name == "nt":
                os.startfile(str(png_path.resolve()))
        except Exception:
            pass

        self.memory.log_agent("gpu", task[:200], f"graph {png_path}")
        return self._report(samples, png_path, csv_path, idle, errors)


    def _plot(self, samples, path, gpu_name, loaded):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        nan = float("nan")
        col = lambda k: [s[k] if s[k] is not None else nan for s in samples]
        t = [s["t"] for s in samples]
        has_power = any(s["power"] is not None for s in samples)
        rows = 4 if has_power else 3

        fig, ax = plt.subplots(rows, 1, figsize=(10, 2.6 * rows), sharex=True)
        ax[0].plot(t, col("util"), color="#2a9d8f", linewidth=2)
        ax[0].set_ylabel("GPU util (%)")
        ax[0].set_ylim(0, 100)

        ax[1].plot(t, col("vram"), color="#e76f51", linewidth=2)
        total = max((s["vram_total"] for s in samples if s["vram_total"]), default=None)
        if total:
            ax[1].axhline(total, color="gray", linestyle="--", linewidth=1)
            ax[1].set_ylim(0, total * 1.08)
        ax[1].set_ylabel("VRAM used (MB)")

        ax[2].plot(t, col("temp"), color="#e9a820", linewidth=2)
        ax[2].set_ylabel("Temp (°C)")

        if has_power:
            ax[3].plot(t, col("power"), color="#6a4c93", linewidth=2)
            ax[3].set_ylabel("Power (W)")

        for a in ax:
            a.grid(alpha=0.3)
        ax[-1].set_xlabel("Seconds")
        fig.suptitle(f"{gpu_name} — {'under llama3 load' if loaded else 'idle'}", fontsize=13)
        fig.tight_layout(rect=[0, 0, 1, 0.96])
        fig.savefig(path, dpi=130)
        plt.close(fig)


    def _report(self, samples, png_path, csv_path, idle, errors):
        vals = lambda k: [s[k] for s in samples if s[k] is not None]
        util, vram, temp, power = vals("util"), vals("vram"), vals("temp"), vals("power")
        total = max(vals("vram_total"), default=0)
        lines = [f"GPU graph saved: {png_path}", f"Raw data saved:  {csv_path}", ""]
        if util:
            lines.append(f"Utilization : avg {sum(util) / len(util):.0f}%  |  peak {max(util):.0f}%")
        if vram:
            lines.append(f"VRAM        : peak {max(vram):.0f} MB of {total:.0f} MB")
        if temp:
            lines.append(f"Temperature : max {max(temp):.0f}°C")
        if power:
            lines.append(f"Power       : avg {sum(power) / len(power):.0f} W  |  peak {max(power):.0f} W")
        if errors:
            lines.append("\nNote: couldn't reach Ollama for the load test, so this graph shows an idle GPU. Start it with: ollama serve")
        elif not idle and util and max(util) < 20:
            lines.append("\nNote: GPU stayed mostly idle — the model may have been slow to load. Run the command again now that it's warm.")
        return "\n".join(lines)
