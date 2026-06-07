"""
Phase 3 Safety: Sandbox policy stubs.

These are *policy helpers* (not full gVisor/Firecracker sandboxes — those come later).
They provide:
- Declarative restrictions
- Check methods that return ActionDecision (so they plug straight into PolicyEngine)
- Easy to compose + serialize (for audit / long-horizon resumption)

Intended usage:
    from agentforge.safety import SandboxPolicy, FileSystemSandbox, CommandSandbox
    from agentforge.safety.policy_engine import PolicyEngine

    fs = FileSystemSandbox(allowed_roots=["/home/eveselove/planlytasksko", "/tmp/agentforge"])
    cmd = CommandSandbox(whitelist=["cargo", "python", "git", "pytest"], deny_patterns=[...])

    # Then either call directly or register as rules:
    engine.add_rule(fs.check_write)
    engine.add_rule(cmd.check_command)
"""

from dataclasses import dataclass, field
from typing import List, Set, Dict, Any, Optional, Pattern, Tuple
import re
from pathlib import Path

from .policy_engine import ActionDecision, Decision


@dataclass
class SandboxPolicy:
    """Base class for all sandbox policies. Subclasses implement check_* methods returning Optional[ActionDecision]."""
    name: str = "base-sandbox"
    enabled: bool = True

    def is_enabled(self) -> bool:
        return self.enabled


@dataclass
class FileSystemSandbox(SandboxPolicy):
    """Controls file system access. MVP focuses on writes + reads outside project roots."""

    allowed_roots: List[str] = field(default_factory=lambda: ["/home/eveselove/planlytasksko", "/tmp/agentforge", "/tmp"])
    denied_paths: List[str] = field(default_factory=lambda: ["/etc", "/boot", "/sys", "/proc", "/root", "/dev"])
    allow_hidden_dotfiles: bool = False   # conservative default

    def _is_path_allowed(self, path: str, for_write: bool = False) -> Tuple[bool, Optional[str]]:
        p = str(path)
        for bad in self.denied_paths:
            if p.startswith(bad):
                return False, f"denied system path prefix: {bad}"
        # Must be under at least one allowed root
        under_root = any(p.startswith(r) or Path(p).resolve().is_relative_to(Path(r).resolve()) for r in self.allowed_roots if Path(r).exists())
        if not under_root and not p.startswith("/tmp/"):
            return False, "outside declared project/worktree roots"
        if not self.allow_hidden_dotfiles and "/." in p.split("/")[-1]:
            # simplistic dotfile guard
            if any(seg.startswith(".") and len(seg) > 1 for seg in Path(p).parts):
                return False, "hidden dotfile access blocked"
        return True, None

    def check_read(self, action_type: str, context: Dict[str, Any]) -> Optional[ActionDecision]:
        if action_type not in ("file_read", "read_file", "open"):
            return None
        path = context.get("path") or context.get("target") or ""
        ok, reason = self._is_path_allowed(str(path), for_write=False)
        if not ok:
            return ActionDecision(Decision.BLOCK, f"FS read blocked: {reason}", policy_name=self.name, risk_score=0.65, metadata={"path": path})
        return None

    def check_write(self, action_type: str, context: Dict[str, Any]) -> Optional[ActionDecision]:
        if action_type not in ("file_write", "file_edit", "write_file", "create_file"):
            return None
        path = context.get("path") or context.get("target") or ""
        ok, reason = self._is_path_allowed(str(path), for_write=True)
        if not ok:
            return ActionDecision(Decision.BLOCK, f"FS write blocked: {reason}", policy_name=self.name, risk_score=0.9, metadata={"path": path})
        # Extra caution on very large writes
        size = context.get("size") or 0
        if isinstance(size, (int, float)) and size > 50 * 1024 * 1024:  # 50MB
            return ActionDecision(Decision.REQUIRE_APPROVAL, "Very large file write", policy_name=self.name, risk_score=0.55)
        return None


@dataclass
class NetworkSandbox(SandboxPolicy):
    """Network restrictions stub. In real deployment this would be enforced at iptables / proxy level too."""

    allowed_hosts: Set[str] = field(default_factory=set)   # empty = everything allowed (MVP permissive)
    denied_hosts: Set[str] = field(default_factory=lambda: {"metadata.google.internal", "169.254.169.254"})
    allow_outbound: bool = True
    max_requests_per_min: int = 120

    def check_network(self, action_type: str, context: Dict[str, Any]) -> Optional[ActionDecision]:
        if action_type not in ("network", "http_request", "curl", "socket_connect"):
            return None
        host = str(context.get("host") or context.get("url") or "").lower()
        for bad in self.denied_hosts:
            if bad in host:
                return ActionDecision(Decision.BLOCK, f"Network denied host: {bad}", policy_name=self.name, risk_score=0.95)
        if self.allowed_hosts and not any(h in host for h in self.allowed_hosts):
            return ActionDecision(Decision.REQUIRE_APPROVAL, "Network destination not on explicit allowlist", policy_name=self.name, risk_score=0.6)
        if not self.allow_outbound:
            return ActionDecision(Decision.BLOCK, "Outbound network disabled by sandbox", policy_name=self.name, risk_score=0.8)
        return None


@dataclass
class CommandSandbox(SandboxPolicy):
    """Command execution restrictions. Complements the regex rules in PolicyEngine."""

    whitelist: List[str] = field(default_factory=lambda: ["cargo", "rustc", "python", "python3", "git", "pytest", "cargo-nextest", "bash", "sh", "make", "npm", "node"])
    deny_patterns: List[str] = field(default_factory=lambda: [r"sudo\s+.*", r"su\s+", r"env\s+.*LD_PRELOAD"])
    max_command_length: int = 600

    def check_command(self, action_type: str, context: Dict[str, Any]) -> Optional[ActionDecision]:
        if action_type != "shell_command":
            return None
        cmd = str(context.get("command") or "").strip()
        if not cmd:
            return None

        if len(cmd) > self.max_command_length:
            return ActionDecision(Decision.REQUIRE_APPROVAL, f"Command length {len(cmd)} exceeds limit", policy_name=self.name, risk_score=0.5)

        first_token = cmd.split()[0]
        if self.whitelist and first_token not in self.whitelist and not any(first_token.startswith(w) for w in self.whitelist):
            return ActionDecision(Decision.REQUIRE_APPROVAL, f"Command '{first_token}' not in sandbox whitelist", policy_name=self.name, risk_score=0.45)

        for pat in self.deny_patterns:
            if re.search(pat, cmd):
                return ActionDecision(Decision.BLOCK, f"Command matched deny pattern {pat}", policy_name=self.name, risk_score=0.9)
        return None


# Convenience: a full "recommended sandbox bundle" for a typical AgentForge Grok worktree
def create_recommended_sandbox_bundle(project_root: str = "/home/eveselove/planlytasksko") -> List[SandboxPolicy]:
    fs = FileSystemSandbox(allowed_roots=[project_root, "/tmp/agentforge", "/tmp"])
    net = NetworkSandbox(allow_outbound=True)
    cmd = CommandSandbox()
    return [fs, net, cmd]
