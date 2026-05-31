# -*- coding: utf-8 -*-
"""
!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
trainer_interface.py — Abstract + concrete trainer interfaces for the (Python) AgentForge Learning Flywheel.

PHASE 4 DELETION TARGET. Python flywheel orchestration DEPRECATED.
MIGRATE TO agentforge-runner + Rust trainer.
Guard: from agentforge.learning.utils import is_pure_rust_flywheel (Phase 4 strengthened)
See utils.py (full list) + PHASE4_REMOVAL_PLAN.md
"""

import json
import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal, Union

from .trajectory_dataset import TrajectoryDataset


# ------------------------------------------------------------------
# Core types
# ------------------------------------------------------------------
@dataclass
class TrainingConfig:
    """Common hyperparameters + pragmatic knobs."""
    method: Literal["dpo", "kto", "sft", "prm", "orpo"] = "dpo"
    model_name: str = "Qwen/Qwen2.5-7B-Instruct"   # or your base policy
    learning_rate: float = 5e-6
    epochs: int = 1
    batch_size: int = 4
    max_length: int = 4096
    beta: float = 0.1               # DPO/KTO strength
    warmup_ratio: float = 0.1
    gradient_accumulation: int = 4
    lora: bool = True
    lora_r: int = 32
    lora_alpha: int = 64
    output_dir: Optional[str] = None
    seed: int = 42
    extra: Dict[str, Any] = field(default_factory=dict)  # pass-through to real trainer


@dataclass
class TrainingRun:
    """Result of a training attempt (or dry-run)."""
    run_id: str
    method: str
    config: TrainingConfig
    prepared_data_path: str
    output_dir: str
    status: Literal["completed", "failed", "dry_run", "submitted"]
    started_at: str
    finished_at: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)  # eval loss, win_rate on heldout, etc.
    artifacts: Dict[str, str] = field(default_factory=dict)  # adapter, merged, logs
    logs: List[str] = field(default_factory=list)
    error: Optional[str] = None


class BaseTrainer(ABC):
    """Abstract trainer. All real trainers inherit from this."""

    name: str = "base"

    def __init__(self, config: Optional[TrainingConfig] = None):
        self.config = config or TrainingConfig()
        self.last_run: Optional[TrainingRun] = None

    @abstractmethod
    def prepare_dataset(
        self,
        dataset: Union[TrajectoryDataset, Path, List[Dict]],
        output_dir: Optional[Path] = None,
        **kwargs,
    ) -> Path:
        """Turn a rich TrajectoryDataset into the exact format the trainer backend expects.
        Must be idempotent and produce a stable directory of JSONL + manifest.
        """
        ...

    @abstractmethod
    def train(
        self,
        prepared_data: Path,
        output_dir: Optional[Path] = None,
        config: Optional[TrainingConfig] = None,
        dry_run: bool = False,
        **kwargs,
    ) -> TrainingRun:
        """Execute (or dry-run) training. Returns a TrainingRun with status + artifacts."""
        ...

    # Convenience
    def run_full_cycle(
        self,
        dataset: TrajectoryDataset,
        base_output: Path,
        config: Optional[TrainingConfig] = None,
        dry_run: bool = True,
    ) -> TrainingRun:
        cfg = config or self.config
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        run_dir = base_output / f"{self.name}_{cfg.method}_{ts}"
        run_dir.mkdir(parents=True, exist_ok=True)

        prepared = self.prepare_dataset(dataset, output_dir=run_dir / "prepared")
        return self.train(prepared, output_dir=run_dir / "model", config=cfg, dry_run=dry_run)


# ------------------------------------------------------------------
# Concrete: DPO / Preference Trainer (most important for flywheel)
# ------------------------------------------------------------------
class DPOTrainer(BaseTrainer):
    """
    DPO / preference tuning trainer.

    Prepares chosen/rejected pairs from TrajectoryDataset.export_preference_pairs().
    Produces the exact format expected by TRL's DPOTrainer, axolotl DPO recipes, etc.
    """

    name = "dpo"

    def prepare_dataset(
        self,
        dataset: Union[TrajectoryDataset, Path, List[Dict]],
        output_dir: Optional[Path] = None,
        min_pair_quality: float = 8.0,
        **kwargs,
    ) -> Path:
        if isinstance(dataset, (str, Path)):
            # Already exported pairs file — just copy/reference
            out = Path(output_dir or "training_ready/dpo") / "preference.jsonl"
            out.parent.mkdir(parents=True, exist_ok=True)
            # In real impl we would validate + possibly reformat
            return Path(dataset)

        if isinstance(dataset, list):
            pairs = dataset
        else:
            pairs = dataset.export_preference_pairs(min_pair_quality=min_pair_quality)

        out_dir = Path(output_dir or "training_ready/dpo")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "preference_pairs.jsonl"

        with open(out_file, "w", encoding="utf-8") as f:
            for p in pairs:
                # Standard DPO format (TRL / axolotl compatible)
                ex = {
                    "prompt": f"Task: {p['benchmark_id']}\n\nImprove your behavior on this type of task.",
                    "chosen": self._render_trajectory(p["chosen"]),
                    "rejected": self._render_trajectory(p["rejected"]),
                    "metadata": {
                        "benchmark_id": p["benchmark_id"],
                        "pair_quality": p.get("pair_quality"),
                        "chosen_prm": p["chosen"].get("prm_overall"),
                        "rejected_prm": p["rejected"].get("prm_overall"),
                    },
                }
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")

        # Write a tiny manifest for the trainer script
        manifest = {
            "method": "dpo",
            "count": len(pairs),
            "min_pair_quality": min_pair_quality,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "source_dataset": getattr(dataset, "name", "unknown"),
        }
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        print(f"[DPOTrainer] Prepared {len(pairs)} preference pairs -> {out_file}")
        return out_file

    def train(
        self,
        prepared_data: Path,
        output_dir: Optional[Path] = None,
        config: Optional[TrainingConfig] = None,
        dry_run: bool = False,
        **kwargs,
    ) -> TrainingRun:
        cfg = config or self.config
        cfg.method = "dpo"
        out_dir = Path(output_dir or f"runs/{self.name}_{datetime.utcnow().strftime('%Y%m%d_%H%M')}")
        out_dir.mkdir(parents=True, exist_ok=True)

        run_id = f"dpo-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        run = TrainingRun(
            run_id=run_id,
            method="dpo",
            config=cfg,
            prepared_data_path=str(prepared_data),
            output_dir=str(out_dir),
            status="dry_run" if dry_run else "submitted",
            started_at=datetime.utcnow().isoformat() + "Z",
        )

        # Pragmatic: write a ready-to-run TRL launch script
        script = out_dir / "launch_dpo.py"
        script.write_text(self._generate_trl_dpo_script(prepared_data, out_dir, cfg), encoding="utf-8")

        if dry_run:
            run.logs.append("DRY RUN — launch script written. Run it with your GPU env when ready.")
            run.artifacts["launch_script"] = str(script)
            run.metrics = {"pairs_prepared": "see manifest"}
            print(f"[DPOTrainer] Dry-run complete. Launch script: {script}")
            return run

        # In real life: subprocess to python launch or torchrun, or call TRL directly
        # For now we keep it safe and explicit.
        run.logs.append("Real training not executed in this pragmatic interface (set dry_run=False + implement executor).")
        run.status = "submitted"
        return run

    def _render_trajectory(self, side: Dict[str, Any]) -> str:
        summary = side.get("summary", {})
        events = side.get("events", [])
        text = f"Outcome: {side.get('outcome')}. PRM: {side.get('prm_overall')}\n"
        for ev in events[-8:]:  # last N steps for context
            et = ev.get("type", "")
            data = ev.get("data", ev)
            if et == "reasoning":
                text += f"  Thought: {data.get('thought', '')[:120]}\n"
            elif et == "tool_call":
                text += f"  Tool: {data.get('tool', '?')} -> {str(data.get('result_preview', ''))[:80]}\n"
        return text.strip()

    def _generate_trl_dpo_script(self, data_path: Path, out_dir: Path, cfg: TrainingConfig) -> str:
        return f'''#!/usr/bin/env python3
"""
Auto-generated DPO training script for AgentForge (TRL).
Run with: python launch_dpo.py   (after pip install trl peft accelerate)
"""
from trl import DPOTrainer, DPOConfig
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig
from datasets import load_dataset
import os

model_name = "{cfg.model_name}"
data_file = "{data_path}"
output = "{out_dir}"

dataset = load_dataset("json", data_files=data_file, split="train")

model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype="auto", device_map="auto")
tok = AutoTokenizer.from_pretrained(model_name)
if tok.pad_token is None:
    tok.pad_token = tok.eos_token

lora_cfg = LoraConfig(r={cfg.lora_r}, lora_alpha={cfg.lora_alpha}, task_type="CAUSAL_LM") if {cfg.lora} else None

training_args = DPOConfig(
    output_dir=output,
    per_device_train_batch_size={cfg.batch_size},
    gradient_accumulation_steps={cfg.gradient_accumulation},
    learning_rate={cfg.learning_rate},
    num_train_epochs={cfg.epochs},
    beta={cfg.beta},
    max_length={cfg.max_length},
    logging_steps=10,
    save_strategy="epoch",
    report_to="none",
)

trainer = DPOTrainer(
    model=model,
    args=training_args,
    train_dataset=dataset,
    tokenizer=tok,
    peft_config=lora_cfg,
)
trainer.train()
trainer.save_model(output + "/final_adapter")
print("DPO training complete. Adapter saved.")
'''


# ------------------------------------------------------------------
# KTO Trainer
# ------------------------------------------------------------------
class KTOTrainer(BaseTrainer):
    name = "kto"

    def prepare_dataset(self, dataset, output_dir=None, **kwargs):
        if isinstance(dataset, TrajectoryDataset):
            kto_records = dataset.export_kto_format()
        else:
            kto_records = list(dataset) if hasattr(dataset, "__iter__") else []

        out_dir = Path(output_dir or "training_ready/kto")
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "kto_data.jsonl"
        with open(out, "w", encoding="utf-8") as f:
            for ex in kto_records:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")
        return out

    def train(self, prepared_data, output_dir=None, config=None, dry_run=True, **kwargs):
        cfg = config or self.config
        cfg.method = "kto"
        out_dir = Path(output_dir or f"runs/kto_{datetime.utcnow().strftime('%Y%m%d_%H%M')}")
        out_dir.mkdir(parents=True, exist_ok=True)

        run = TrainingRun(
            run_id=f"kto-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            method="kto",
            config=cfg,
            prepared_data_path=str(prepared_data),
            output_dir=str(out_dir),
            status="dry_run" if dry_run else "submitted",
            started_at=datetime.utcnow().isoformat() + "Z",
        )
        run.artifacts["launch_script"] = str(out_dir / "launch_kto.py")
        # Similar script generation omitted for brevity (identical pattern to DPO)
        print(f"[KTOTrainer] Prepared data + stub. Ready for real KTO training backend.")
        return run


# ------------------------------------------------------------------
# SFT Trainer (simplest & very effective on our success trajectories)
# ------------------------------------------------------------------
class SFTTrainer(BaseTrainer):
    name = "sft"

    def prepare_dataset(self, dataset, output_dir=None, only_success=True, **kwargs):
        if isinstance(dataset, TrajectoryDataset):
            out_path = dataset.export_sft_jsonl(
                path=Path(output_dir or "training_ready/sft") / "sft.jsonl",
                only_success=only_success,
            )
            return out_path
        # If already a path, return it
        return Path(dataset)

    def train(self, prepared_data, output_dir=None, config=None, dry_run=True, **kwargs):
        cfg = config or self.config
        cfg.method = "sft"
        out_dir = Path(output_dir or f"runs/sft_{datetime.utcnow().strftime('%Y%m%d_%H%M')}")
        out_dir.mkdir(parents=True, exist_ok=True)

        run = TrainingRun(
            run_id=f"sft-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            method="sft",
            config=cfg,
            prepared_data_path=str(prepared_data),
            output_dir=str(out_dir),
            status="dry_run" if dry_run else "submitted",
            started_at=datetime.utcnow().isoformat() + "Z",
        )
        print("[SFTTrainer] SFT data ready. Extremely effective first training step on high-quality successes.")
        return run


# ------------------------------------------------------------------
# Registry + factory (makes plugging new methods trivial)
# ------------------------------------------------------------------
TRAINER_REGISTRY: Dict[str, type[BaseTrainer]] = {
    "dpo": DPOTrainer,
    "kto": KTOTrainer,
    "sft": SFTTrainer,
    "preference": DPOTrainer,
}

def get_trainer(method: str, config: Optional[TrainingConfig] = None) -> BaseTrainer:
    cls = TRAINER_REGISTRY.get(method.lower(), DPOTrainer)
    return cls(config=config)


__all__ = [
    "BaseTrainer",
    "TrainingConfig",
    "TrainingRun",
    "DPOTrainer",
    "KTOTrainer",
    "SFTTrainer",
    "get_trainer",
    "TRAINER_REGISTRY",
]
