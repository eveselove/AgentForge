"""
Core data schemas for the AgentForge Evaluation Framework.

This is the foundation for turning AgentForge into a system that can
compete with the best agentic engineering teams (Anthropic, Cognition, etc.).

Design principles:
- Every task must be reproducible and objectively verifiable.
- Rich metadata for slicing results (by difficulty, category, agent, etc.).
- Support for multiple verification strategies.
- Rich enough for future Process Reward Models and learning.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any


class TaskOutcome(str, Enum):
    """Final outcome of an evaluation run."""
    SUCCESS = "success"
    PARTIAL = "partial"       # Solved most of it, but not fully correct
    FAILED = "failed"
    TIMEOUT = "timeout"
    ERROR = "error"           # Crashed or unrecoverable error


class VerificationMethod(str, Enum):
    """
    How we determine whether a task was solved correctly.
    Order of preference: objective → subjective.
    """
    TESTS_PASS = "tests_pass"                 # Best: automated tests
    GOLDEN_DIFF = "golden_diff"               # Compare git diff against known correct solution
    PROPERTY_CHECKS = "property_checks"       # Custom invariants / semantic checks
    MANUAL_REVIEW = "manual_review"           # Human review required
    LLM_JUDGE = "llm_judge"                   # Use strong model as judge (use sparingly)


@dataclass
class BenchmarkTask:
    """
    A single, high-quality benchmark task for evaluating agents.

    Requirements for a good benchmark task:
    - Taken from real production work (not synthetic toys)
    - Has clear, objective success criteria
    - Reproducible environment
    - Tagged for analysis (difficulty, category, skills required)
    """
    id: str
    title: str
    description: str

    # Execution context
    repo_path: str = "/home/eveselove/planlytasksko"
    base_branch: str = "main"

    # Verification (how do we know it succeeded?)
    verification: VerificationMethod = VerificationMethod.TESTS_PASS
    verification_command: Optional[str] = None   # Shell command that must exit 0
    golden_patch: Optional[str] = None           # Expected diff for GOLDEN_DIFF method

    # Rich metadata (critical for analysis)
    difficulty: str = "medium"          # easy | medium | hard | expert
    category: str = "general"           # rust | refactoring | performance | architecture | bugfix | feature | crawler | etc.
    tags: List[str] = field(default_factory=list)
    estimated_minutes: int = 30
    required_skills: List[str] = field(default_factory=list)  # e.g. ["rust", "adaptive-throttling", "proxies"]

    # Extra context that can be injected into the agent's prompt
    extra_context: Dict[str, Any] = field(default_factory=dict)

    # Provenance
    source_chat: Optional[str] = None   # e.g. chat ID where this task originally appeared
    created_at: datetime = field(default_factory=datetime.utcnow)
    version: str = "1.0"                # For tracking evolution of the benchmark

    def to_prompt_context(self) -> str:
        """Generate a clean description suitable for injecting into an agent prompt."""
        ctx = f"**Задача:** {self.title}\n\n{self.description}\n\n"
        if self.extra_context:
            ctx += "**Дополнительный контекст:**\n"
            for k, v in self.extra_context.items():
                ctx += f"- {k}: {v}\n"
        return ctx.strip()


@dataclass
class EvaluationResult:
    """
    Complete result of evaluating one agent on one benchmark task.

    This object is the primary artifact we use for:
    - Measuring progress over time
    - Comparing agents and skills
    - Training data (trajectories + outcomes)
    - Regression detection
    """
    # Required fields must come first (dataclass rule: no non-default fields after defaults)
    task_id: str
    agent: str                          # grok / jules / antigravity / ...
    outcome: TaskOutcome
    duration_seconds: float

    # Optional fields (all have defaults)
    model: Optional[str] = None

    # Efficiency & Cost metrics (extremely important)
    steps_taken: int = 0
    tool_calls: int = 0
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0

    # Outcome details
    final_diff: Optional[str] = None
    test_results: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    recovery_attempts: int = 0          # How many times the agent had to recover from errors

    # Link to rich data
    trajectory_path: Optional[str] = None   # Full structured log (for learning)
    worktree_path: Optional[str] = None     # Where the agent actually worked

    # Process Reward Model (Phase 1) — step-level quality signals
    prm_overall_score: Optional[float] = None
    prm_high_quality_steps: Optional[int] = None
    prm_low_quality_steps: Optional[int] = None
    prm_suggestions: Optional[List[str]] = None   # Top process improvement hints

    # Human or strong-model judgment (for cases without objective verification)
    quality_score: Optional[float] = None   # 0.0 – 1.0
    judge_notes: Optional[str] = None

    # Real execution linkage
    real_task_id: Optional[str] = None   # When this result came from a real AgentForge task

    evaluated_at: datetime = field(default_factory=datetime.utcnow)

    def is_success(self) -> bool:
        return self.outcome == TaskOutcome.SUCCESS

    def efficiency_score(self) -> float:
        """Simple efficiency heuristic (higher is better)."""
        if not self.is_success():
            return 0.0
        if self.duration_seconds <= 0:
            return 0.0
        return (1.0 / (self.duration_seconds + 1)) * (1.0 / (self.cost_usd + 0.01)) * 100


@dataclass
class AgentQualityReport:
    """Aggregated report for one or more agents over a set of tasks."""
    agent: str
    total_tasks: int
    success_rate: float
    avg_duration_seconds: float
    avg_cost_usd: float
    avg_steps: float
    total_cost_usd: float

    by_category: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    by_difficulty: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    generated_at: datetime = field(default_factory=datetime.utcnow)
