"""
Phase 3: Safety & Policy foundations.

Strong practical skeleton:
- PolicyEngine + composable rules (fast allow/block/require)
- SandboxPolicy stubs (FileSystem, Network, Command) — plug straight into engine
- ActionApprovalLayer — the high-level gate most agent code should call (risk scoring + optional HITL hook)

Usage (recommended):
    from agentforge.safety import create_default_approval_layer, Decision
    approver = create_default_approval_layer()
    dec = approver.approve("shell_command", {"command": "rm -rf /tmp/foo"})
"""

from .policy_engine import (
    PolicyEngine,
    ActionDecision,
    Decision,
    create_default_policy_engine,
)
from .sandbox import (
    SandboxPolicy,
    FileSystemSandbox,
    NetworkSandbox,
    CommandSandbox,
    create_recommended_sandbox_bundle,
)
from .approval import (
    ActionApprovalLayer,
    create_default_approval_layer,
)

__all__ = [
    "PolicyEngine",
    "ActionDecision",
    "Decision",
    "create_default_policy_engine",
    "SandboxPolicy",
    "FileSystemSandbox",
    "NetworkSandbox",
    "CommandSandbox",
    "create_recommended_sandbox_bundle",
    "ActionApprovalLayer",
    "create_default_approval_layer",
]
