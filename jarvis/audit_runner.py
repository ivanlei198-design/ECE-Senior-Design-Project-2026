import argparse
import os
from pathlib import Path

from memory.persistent_memory import PersistentMemory
from mcp.mcp_router import MCPRouter
from agents.base_agent import BaseAgent, run_captured
from agents.cybersec_agent import CyberSecAgent, FRAMEWORKS


def main():
    ap = argparse.ArgumentParser(description="Run a security audit in this window.")
    ap.add_argument("--ip", required=True, help="IP address of the computer to audit")
    ap.add_argument("--user", required=True, help="SSH username on that computer")
    ap.add_argument("--framework", choices=list(FRAMEWORKS), default=None,
                    help="frame the report for: " + ", ".join(FRAMEWORKS))
    ap.add_argument("--status-file", default=None, help="where to report progress (set by the watcher)")
    ap.add_argument("--attempt", type=int, default=1, help="which attempt this is (set by the watcher)")
    args = ap.parse_args()

    if os.name == "nt":
        os.system(f"title Security Audit - {args.ip} (attempt {args.attempt})")

    agent = CyberSecAgent(PersistentMemory(), MCPRouter())
    agent.current_ip, agent.current_user = args.ip, args.user
    if args.status_file:
        agent.status_file, agent.attempt = Path(args.status_file), args.attempt
        BaseAgent.progress_hook = agent.touch_progress

    try:
        _, shown = run_captured(agent._full_audit, args.framework)
        if shown:
            print(shown)
    except KeyboardInterrupt:
        print("\nAudit cancelled.")
        agent._status("cancelled", "cancelled by the user (Ctrl+C in the audit window)", retryable=False)
    except Exception as e:
        print(f"\nAudit failed: {e}")
        agent._status("failed", f"unexpected error: {e}", retryable=True)

    try:
        input("\nPress Enter to close this window...")
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    main()
