"""
Phase 3 Safety: Policy Engine (core) + integration points.

Rules are pure callables: (action_type: str, context: dict) -> Optional[ActionDecision]

The engine short-circuits on first non-None decision (order matters — register most specific first).

Built-in example policies included. Designed to be called from:
- Runners before dangerous shell / edit / net ops
- Skill execution wrappers

CONVERGED DUAL (20 Grok + 3 Agy terminals 2026-06-13 wave): under pure delegates to agentforge-runner.
See audit in REMAINING, task-2cec828e/task-5af0e350, JULES f29c675b.

- Long-horizon execution engine
- MCP tool dispatch

See sandbox.py and approval.py for higher layers.
"""

from dataclasses import dataclass
from typing import List, Callable, Dict, Any, Optional
from enum import Enum
import re


class Decision(Enum):
    ALLOW = "allow"
    BLOCK = "block"
    REQUIRE_APPROVAL = "require_approval"


@dataclass
class ActionDecision:
    decision: Decision
    reason: str
    policy_name: Optional[str] = None
    risk_score: float = 0.0  # 0.0 (safe) .. 1.0 (extremely dangerous)
    metadata: Dict[str, Any] = None  # extra context (e.g. matched pattern)

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class PolicyEngine:
    """Core policy engine. Lightweight, fast, easily persisted as rule names + params."""

    def __init__(self, name: str = "default"):
        self.name = name
        self.rules: List[Callable[[str, Dict[str, Any]], Optional[ActionDecision]]] = []
        self.rule_names: Dict[int, str] = {}  # id(rule) -> friendly name for debugging

    def add_rule(self, rule: Callable, name: Optional[str] = None):
        self.rules.append(rule)
        if name:
            self.rule_names[id(rule)] = name

    def evaluate(self, action_type: str, context: Dict[str, Any]) -> ActionDecision:
        """
        Evaluate all rules in registration order.
        First rule that returns non-None wins.
        Always returns a decision (defaults to ALLOW with risk 0).
        """
        for rule in self.rules:
            try:
                decision = rule(action_type, context or {})
                if decision:
                    if decision.policy_name is None:
                        decision.policy_name = self.rule_names.get(
                            id(rule),
                            rule.__name__ if hasattr(rule, "__name__") else "anonymous",
                        )
                    return decision
            except Exception as e:
                # Never let a bad policy crash the agent — fail closed to REQUIRE_APPROVAL
                return ActionDecision(
                    Decision.REQUIRE_APPROVAL,
                    f"Policy evaluation error in {self.rule_names.get(id(rule), 'rule')}: {e}",
                    policy_name="policy_engine_safety",
                    risk_score=0.8,
                )
        return ActionDecision(
            Decision.ALLOW, "No blocking policy matched", risk_score=0.0
        )

    # ===================== Built-in high-value policies (register these by default) =====================

    @staticmethod
    def no_dangerous_commands(
        action_type: str, context: Dict
    ) -> Optional[ActionDecision]:
        if action_type != "shell_command":
            return None
        cmd = (context.get("command") or "").lower().strip()
        dangerous_patterns = [
            r"rm\s+-rf\s+/",
            r"rm\s+-rf\s+\*",
            r"dd\s+if=",
            r":\(\)\s*\{.*\}\s*;",  # fork bomb
            r"shutdown",
            r"reboot",
            r"halt",
            r"poweroff",
            r"mkfs",
            r"format\s+",
            r"wipefs",
            r"curl.*\|\s*(bash|sh)",
            r"wget.*\|\s*(bash|sh)",
            r"sudo\s+rm\s+-rf",
        ]
        for pat in dangerous_patterns:
            if re.search(pat, cmd):
                return ActionDecision(
                    Decision.BLOCK,
                    f"Dangerous command pattern matched: {pat}",
                    risk_score=0.95,
                    metadata={"matched": pat, "cmd": cmd[:200]},
                )
        # Very long or complex commands get soft flag
        if len(cmd) > 800:
            return ActionDecision(
                Decision.REQUIRE_APPROVAL,
                "Extremely long shell command",
                risk_score=0.6,
            )
        return None

    @staticmethod
    def no_unbounded_file_writes(
        action_type: str, context: Dict
    ) -> Optional[ActionDecision]:
        if action_type not in ("file_write", "file_edit", "write_file"):
            return None
        path = str(context.get("path") or context.get("target") or "").lower()
        risky = [
            p
            for p in (
                "/etc",
                "/boot",
                "/sys",
                "/proc",
                "/root",
                "/dev",
                "/lib",
                "/usr/lib",
            )
            if p in path
        ]
        if risky:
            return ActionDecision(
                Decision.REQUIRE_APPROVAL,
                f"Attempt to write to sensitive system path: {risky[0]}",
                risk_score=0.85,
                metadata={"path": path},
            )
        # Outside project or /tmp is also notable
        if not (
            "/home" in path
            or "/tmp/agentforge" in path
            or "planlytasksko" in path
            or path.startswith("/tmp/")
        ):
            return ActionDecision(
                Decision.REQUIRE_APPROVAL,
                "Write outside normal project/worktree area",
                risk_score=0.55,
            )
        return None

    @staticmethod
    def high_risk_network(action_type: str, context: Dict) -> Optional[ActionDecision]:
        if action_type not in ("network", "http", "curl", "wget", "socket"):
            return None
        url = str(context.get("url") or context.get("host") or "").lower()
        if any(
            bad in url for bad in ["localhost", "127.0.0.1", "169.254"]
        ):  # metadata services etc.
            return ActionDecision(
                Decision.REQUIRE_APPROVAL,
                "Network call targeting localhost/metadata endpoint",
                risk_score=0.7,
            )
        if context.get("method", "GET").upper() in ("POST", "PUT", "PATCH", "DELETE"):
            return ActionDecision(
                Decision.REQUIRE_APPROVAL, "Mutating network request", risk_score=0.4
            )
        return None


def create_default_policy_engine() -> PolicyEngine:
    """Factory with the most important guardrails pre-registered. Use this in production paths."""
    engine = PolicyEngine("agentforge-default-v1")
    engine.add_rule(PolicyEngine.no_dangerous_commands, "no_dangerous_commands")
    engine.add_rule(PolicyEngine.no_unbounded_file_writes, "no_unbounded_file_writes")
    engine.add_rule(PolicyEngine.high_risk_network, "high_risk_network")
    return engine
