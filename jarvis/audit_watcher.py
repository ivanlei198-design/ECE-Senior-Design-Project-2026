import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from tools.notifier import email_enabled, email_target, send_email
from tools.status_board import AGENT_HEARTBEAT, STATUS_DIR, read_status

HERE = Path(__file__).resolve().parent
NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010)


def say(tag: str, msg: str):
    print(f"[{datetime.now():%H:%M:%S}] {tag:<5} {msg}", flush=True)


def launch(args, status_path: Path, attempt: int):
    argv = [sys.executable, str(HERE / "audit_runner.py"), "--ip", args.ip, "--user", args.user,
            "--status-file", str(status_path), "--attempt", str(attempt)]
    if args.framework:
        argv += ["--framework", args.framework]
    if os.name == "nt":
        return subprocess.Popen(argv, cwd=str(HERE), creationflags=NEW_CONSOLE)
    log = open(STATUS_DIR / f"audit_attempt{attempt}.log", "w")
    return subprocess.Popen(argv, cwd=str(HERE), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)


def stop(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def main():
    ap = argparse.ArgumentParser(description="Watch a security audit and restart it if it fails.")
    ap.add_argument("--ip", required=True)
    ap.add_argument("--user", required=True)
    ap.add_argument("--framework", default=None)
    ap.add_argument("--max-attempts", type=int, default=3, help="total tries, including the first")
    ap.add_argument("--stall", type=int, default=120, help="seconds without progress before the audit counts as stuck")
    ap.add_argument("--agent-stale", type=int, default=15, help="seconds without a heartbeat before terminal 1 counts as gone")
    args = ap.parse_args()

    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    status_path = STATUS_DIR / f"audit_{args.ip.replace('.', '_')}_{datetime.now():%Y%m%d_%H%M%S}.json"
    if os.name == "nt":
        os.system(f"title Audit Watcher - {args.ip}")
    label = f"{args.ip}" + (f" for {args.framework}" if args.framework else "")

    print("=" * 66)
    print(f"  AUDIT WATCHER — monitoring the audit of {label}")
    print(f"  restarts after {args.stall}s without progress  |  max {args.max_attempts} attempts")
    print(f"  email alerts: " + (f"ON -> {email_target()}" if email_enabled()
                                else "OFF (set SDP_SMTP_HOST and SDP_NOTIFY_TO to enable)"))
    print("  Ctrl+C here stops the watcher and the audit")
    print("=" * 66)

    def notify(tag: str, subject: str, body: str):
        say(tag, subject)
        if email_enabled():
            ok, info = send_email(f"[SDP audit] {subject}", body)
            say("MAIL", info if ok else f"email failed: {info}")

    attempt, started_all = 1, time.time()
    proc = launch(args, status_path, attempt)
    launched_at = last_print = time.time()
    last_state, last_step, agent_seen = None, -1, None
    say("INFO", f"Audit started in terminal 2 (attempt {attempt}/{args.max_attempts})")

    def give_up_or_restart(reason: str):
        nonlocal attempt, proc, launched_at, last_state, last_step
        stop(proc)
        if attempt >= args.max_attempts:
            return False
        attempt += 1
        say("WARN", reason)
        notify("WARN", f"Restarting the audit of {label} (attempt {attempt}/{args.max_attempts})",
               f"{reason}\n\nThe watcher is starting the audit again.")
        proc = launch(args, status_path, attempt)
        launched_at = time.time()
        last_state, last_step = None, -1
        return True

    try:
        while True:
            time.sleep(1)
            now = time.time()


            hb = read_status(AGENT_HEARTBEAT)
            if not hb:
                agent_now = "unknown"
            elif hb.get("closed"):
                agent_now = "closed"
            elif now - hb.get("heartbeat", 0) > args.agent_stale:
                agent_now = "not responding"
            else:
                agent_now = "running"
            if agent_now != agent_seen:
                if agent_now == "running":
                    say("INFO", "Agent terminal (1): running")
                elif agent_now == "unknown" and agent_seen is None:
                    say("INFO", "Agent terminal (1): no heartbeat found (was this watcher started by hand?)")
                elif agent_now != "unknown":
                    say("WARN", f"Agent terminal (1) is {agent_now} — the audit keeps running on its own")
                agent_seen = agent_now


            st = read_status(status_path)
            mine = st if st.get("attempt") == attempt else {}
            state, detail = mine.get("state"), mine.get("detail", "")
            progress = max(mine.get("progress", 0), launched_at)

            if state != last_state or (state == "collecting" and mine.get("step", 0) // 5 != last_step):
                if state == "collecting":
                    last_step = mine.get("step", 0) // 5
                    say("INFO", f"Collecting data {mine.get('step', 0)}/{mine.get('total', '?')}: {detail}")
                elif state == "analyzing":
                    say("INFO", "All checks finished — the AI model is writing the report")
                elif state == "waiting":
                    say("INFO", "Terminal 2 is waiting for the VM password — type it there")
                elif state in ("starting", "done", "failed", "cancelled", None):
                    pass
                last_state, last_print = state, now

            if state == "done":
                score = f", model's score {mine['score']}" if mine.get("score") else ""
                took = int(now - started_all)
                notify("DONE", f"Audit of {label} complete (attempt {attempt}, {took}s{score})",
                       f"Target: {args.ip}\nFramework: {args.framework or 'general'}\nAttempts used: {attempt}\n"
                       f"Report: {mine.get('report')}\nScore reported by the model: {mine.get('score') or 'n/a'}\n"
                       f"Note: an AI-generated informational assessment, not a formal audit.")
                say("INFO", f"Report: {mine.get('report')}")
                break
            if state == "cancelled":
                notify("STOP", f"Audit of {label} was cancelled", mine.get("detail", "cancelled"))
                break
            if state == "failed":
                reason = f"The audit reported a problem: {detail}"
                if mine.get("retryable") and give_up_or_restart(reason):
                    continue
                say("FAIL", reason)
                notify("FAIL", f"Audit of {label} stopped" + (f" after {attempt} attempts" if mine.get("retryable") else ""),
                       f"{reason}\nTarget: {args.ip}" + ("\nRetrying won't help until that is fixed." if not mine.get("retryable") else ""))
                break

            if proc.poll() is not None:
                reason = (f"The audit window closed or crashed before finishing (exit code {proc.returncode}). "
                          f"Last known step: {detail or 'it never reported any status'}")
            elif state == "waiting":
                continue
            elif now - progress > args.stall:
                reason = f"No progress for {int(now - progress)}s (stuck at: {detail or 'start-up'}). The stuck audit was stopped."
            else:
                if now - last_print > 30:
                    say("INFO", f"Still working — {detail or 'starting'} (last progress {int(now - progress)}s ago)")
                    last_print = now
                continue
            if not give_up_or_restart(reason):
                say("FAIL", reason)
                notify("FAIL", f"Audit of {label} failed after {attempt} attempts", reason)
                break
    except KeyboardInterrupt:
        stop(proc)
        say("STOP", "Watcher cancelled — the audit was stopped.")

    try:
        input("\nPress Enter to close this window...")
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    main()
