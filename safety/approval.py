"""
Phase 3 Safety: Action Approval + Risk Scoring Layer.

High-level facade that most code should use:

    from agentforge.safety import ActionApprovalLayer, create_default_approval_layer

    approver = create_default_approval_layer()
    decision = approver.approve("shell_command", {"command": "cargo test"})
    if decision.decision == Decision.BLOCK:
        ... abort or log ...
    elif decision.decision == Decision.REQUIRE_APPROVAL:
        ... ask human / HITL queue ...

Risk scoring is additive and normalized.
Supports:
- Automatic policy engine
- Pluggable risk scorers (callables that return 0-1 float)
- Optional human approval callback hook (for long-horizon interactive mode)
"""

from dataclasses import dataclass, field
from typing import List, Callable, Dict, Any, Optional
from .policy_engine import PolicyEngine, ActionDecision, Decision, create_default_policy_engine
from .sandbox import create_recommended_sandbox_bundle, SandboxPolicy


RiskScorer = Callable[[str, Dict[str, Any]], float]   # returns [0.0, 1.0]


@dataclass
class ActionApprovalLayer:
    """
    The main safety gate for autonomous agents.
    Composes PolicyEngine + Sandboxes + custom risk scorers + optional HITL hook.
    """

    policy_engine: PolicyEngine = field(default_factory=create_default_policy_engine)
    sandboxes: List[SandboxPolicy] = field(default_factory=list)
    extra_risk_scorers: List[RiskScorer] = field(default_factory=list)
    # Optional callback: (action_type, context, tentative_decision) -> bool (True = human approved)
    human_approval_hook: Optional[Callable[[str, Dict[str, Any], ActionDecision], bool]] = None

    def register_sandbox(self, sb: SandboxPolicy):
        self.sandboxes.append(sb)

    def add_risk_scorer(self, scorer: RiskScorer):
        self.extra_risk_scorers.append(scorer)

    def _compute_risk(self, action_type: str, context: Dict[str, Any], base: float) -> float:
        risk = base
        for scorer in self.extra_risk_scorers:
            try:
                risk += scorer(action_type, context or {})
            except Exception:
                risk += 0.1  # conservative
        return max(0.0, min(1.0, risk))

    def approve(self, action_type: str, context: Dict[str, Any]) -> ActionDecision:
        """Primary entrypoint. Returns final ActionDecision (possibly after human hook)."""
        # 1. Policy engine (includes built-in dangerous patterns)
        decision = self.policy_engine.evaluate(action_type, context)

        # 2. Run every registered sandbox
        for sb in self.sandboxes:
            if not sb.is_enabled():
                continue
            for attr in dir(sb):
                if attr.startswith("check_"):
                    checker = getattr(sb, attr)
                    if callable(checker):
                        try:
                            sb_dec = checker(action_type, context)
                            if sb_dec and sb_dec.decision != Decision.ALLOW:
                                # Sandbox is strict — it can only make things worse (more restrictive)
                                if sb_dec.risk_score > decision.risk_score:
                                    decision = sb_dec
                        except Exception:
                            pass

        # 3. Additional risk scoring
        final_risk = self._compute_risk(action_type, context, decision.risk_score)
        decision.risk_score = final_risk

        # 4. If risk is extremely high, force REQUIRE_APPROVAL even if policies said ALLOW
        if final_risk > 0.92 and decision.decision == Decision.ALLOW:
            decision = ActionDecision(
                Decision.REQUIRE_APPROVAL,
                f"Composite risk score {final_risk:.2f} exceeds autonomous threshold",
                policy_name="risk_scorer",
                risk_score=final_risk,
            )

        # 5. Human-in-the-loop hook (long-horizon / critical tasks)
        if decision.decision == Decision.REQUIRE_APPROVAL and self.human_approval_hook:
            try:
                approved = self.human_approval_hook(action_type, context, decision)
                if approved:
                    decision = ActionDecision(
                        Decision.ALLOW,
                        "Approved by human via approval hook",
                        policy_name=decision.policy_name or "human",
                        risk_score=decision.risk_score,
                        metadata={**decision.metadata, "human_approved": True},
                    )
            except Exception as e:
                decision.reason = f"{decision.reason} | Human hook failed: {e}"

        return decision


def create_default_approval_layer(
    project_root: str = "/home/agx/planlytasksko",
    enable_human_hook: bool = False,
) -> ActionApprovalLayer:
    """Ready-to-use production-grade approval layer for most AgentForge workloads."""
    layer = ActionApprovalLayer()
    # Sandboxes
    for sb in create_recommended_sandbox_bundle(project_root):
        layer.register_sandbox(sb)

    # A couple of pragmatic extra risk scorers (easy to extend)
    def risky_file_count_scorer(action_type: str, ctx: Dict) -> float:
        if action_type in ("file_write", "file_edit"):
            # Many simultaneous edits = higher risk of cascading mistakes
            count = ctx.get("files_affected", 1)
            return min(0.35, (count - 1) * 0.08)
        return 0.0

    def long_running_action_scorer(action_type: str, ctx: Dict) -> float:
        timeout = ctx.get("timeout_seconds", 0)
        if timeout and timeout > 1800:  # >30min
            return 0.25
        return 0.0

    layer.add_risk_scorer(risky_file_count_scorer)
    layer.add_risk_scorer(long_running_action_scorer)

    # Human hook is opt-in (for very long horizon tasks or when running with --require-approval)
    if enable_human_hook:
        # Default hook just prints and waits (demo). Real impl talks to dashboard / HITL queue.
        def _demo_hook(action_type, context, decision):
            print(f"[SAFETY] ⚠️  Human approval required for {action_type}: {decision.reason}")
            print(f"         Context keys: {list(context.keys())[:6]}")
            resp = input("Approve? [y/N]: ").strip().lower()
            return resp in ("y", "yes")
        layer.human_approval_hook = _demo_hook

    return layer
