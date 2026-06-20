#!/usr/bin/env python3
"""
bin/swarm-engage.py — thin shim / forwarder.

The real implementation lives in Rust:
  agentforge-runner swarm-engage --prompt-dir ... --name ... --count ...

This py detects the Rust binary (target/release or debug or in PATH) and execs it
with the same args if the subcommand is supported. Otherwise prints guidance.

See docs/PROBLEM_GROK_TMUX_DISPATCH_20260614.md for full usage, the "роевой режим",
how Antigravity hands you one task and you (Grok) drive 50-300 agents directly.
"""

import os
import sys
import subprocess

def find_rust():
    cands = [
        os.path.expanduser("~/agentforge/rust/target/release/agentforge-runner"),
        os.path.expanduser("~/agentforge/rust/target/debug/agentforge-runner"),
    ]
    for p in cands:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            try:
                helptext = subprocess.check_output([p, "--help"], text=True, stderr=subprocess.STDOUT, timeout=5)
                if "swarm-engage" in helptext or "SWARM DIRECT" in helptext:
                    return p
            except Exception:
                continue
    # PATH
    try:
        p = subprocess.check_output(["which", "agentforge-runner"], text=True, stderr=subprocess.DEVNULL).strip()
        if p:
            helptext = subprocess.check_output([p, "--help"], text=True, stderr=subprocess.STDOUT, timeout=5)
            if "swarm-engage" in helptext or "SWARM DIRECT" in helptext:
                return p
    except Exception:
        pass
    return None

def main():
    runner = find_rust()
    if runner:
        os.execvp(runner, [runner, "swarm-engage"] + sys.argv[1:])
    else:
        print("agentforge-runner swarm-engage not found (build it: cd rust && cargo build -p agentforge-runner --release).", file=sys.stderr)
        print("See docs/PROBLEM_GROK_TMUX_DISPATCH_20260614.md for the direct swarm (push) mode.", file=sys.stderr)
        print("Usage (once built): agentforge-runner swarm-engage --help", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
