# AgentForge Learning Module (Phase 1+)

This directory contains tools and documentation for turning evaluation data into training data for improving the agents.

## Current Status

We have a solid **Phase 0 → Phase 1 bridge** (PRM deeply integrated):

- Rich structured trajectories + **PRM scores** (via `load_trajectory(..., include_prm=True)`)
- Evaluation outcomes + **prm_overall_score / high/low step counts** in `../results/`
- Longitudinal history records **PRM fields** via extra (trends + avg_prm in summaries)
- `generate_evaluation_report` has first-class PRM section (per-benchmark trends table + alerts in Exec Summary + Recommended Actions)
- `analyze_trajectories` + `insights` + `suggest` + dashboard all PRM-aware (avg step quality, low-PRM-success detection, etc.)
- `prm` + `view` + `view --prm --html` CLI (interactive timeline + PRM heatmap + live JS filters) powered by `load_trajectory(..., include_prm=True)`
- Powerful exporter: `python -m agentforge.eval export`

The exporter can now produce two main artifacts:

1. **Flat learning records** (good for PRM, critic training, regression analysis)
2. **Preference pairs** (`--generate-pairs`) — chosen (success) vs rejected (failure) for the same benchmark. This is the direct input for DPO, KTO, SimPO, etc.

## How to Generate Training Data

### 1. Basic flat records (most common)

```bash
python -m agentforge.eval export
# or with full trajectories (heavy but powerful for critic models)
python -m agentforge.eval export --include-trajectories --only-real

# With full PRM step-level scores (recommended for Phase 1+ PRM / critic training)
python -m agentforge.eval export --with-prm --include-trajectories --only-real
```

Output goes to `../learning_datasets/learning_dataset_*.jsonl`

### 2. Preference pairs for DPO-style training (recommended for next phase)

```bash
python -m agentforge.eval export --generate-pairs
# You can combine filters:
python -m agentforge.eval export --generate-pairs --only-real --since-days 30

# Pairs + PRM scores (even richer signal for training)
python -m agentforge.eval export --generate-pairs --with-prm --only-real
```

This produces files like `learning_dataset_pairs_*.jsonl` where each line is:

```json
{
  "benchmark_id": "lancedb_parser_bottleneck",
  "chosen": {
    "outcome": "success",
    "trajectory_path": "...",
    "duration_seconds": 187.4,
    "learning_value_score": 42.3
  },
  "rejected": {
    "outcome": "failed",
    "trajectory_path": "...",
    "duration_seconds": 312.1,
    "error_message": "...",
    "learning_value_score": 67.8
  },
  "pair_quality": 55.05
}
```

Higher `pair_quality` = more valuable training signal.

## Using the Data for Training

### For Process Reward Models (PRM) / Outcome Reward Models (ORM)
- Use `--with-prm --include-trajectories` for the richest format
- Each record now includes `prm_step_labels` (per-step scores with reasons/confidence) + richer events from inside execution (llm_turn, tool_result, decision, error_recovery etc. when protocol is active)
- LLM-as-Judge mode available (`--llm-judge` / env) for higher-quality labels
- This is the cleanest ready-to-use format for training step-level PRMs / critics
- **Explore any trajectory visually first** (huge for dataset curation):
  ```bash
  python -m agentforge.eval view 4adb110e --prm --html   # real artifact + interactive PRM heatmap
  python -m agentforge.eval prm f12a11c0 --llm-judge
  ```
  Then `load_trajectory("f12a11c0", include_prm=True)` inside your training scripts.

### For Preference Tuning (DPO / KTO / ORPO)
- Use the pairs export
- `chosen` trajectory/context is the preferred completion
- `rejected` is the worse one

### Future Ideas (Phase 2)
- Automatic step-level labeling from trajectories
- Synthetic hard negatives generation
- Critique data from `judge_notes` and human feedback
- A/B testing of improved skills/prompts using the same benchmarks

## Directory Layout

```
eval/
├── learning/                  # This directory (documentation + future tools)
│   └── README.md
├── learning_datasets/         # Output of the exporter (gitignored recommended)
├── results/                   # Raw EvaluationResult JSONs
├── trajectories/              # Structured .jsonl event logs
├── history/                   # Longitudinal success/failure per benchmark
└── export_learning_dataset.py # The main bridge tool
```

## Next Steps (when we have more real data)

1. Run many real benchmarks (`run-all --real --wait`).
2. Export pairs regularly.
3. Fine-tune a small critic or policy on the pairs.
4. Use the improved model inside the runners (self-improvement loop).

---

**This is the foundation for AgentForge to start learning from its own experience.**

"плавно в идеал" — we now have the data pipeline. The next real gains will come when we have volume + actual training runs on top of it.