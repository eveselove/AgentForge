//! Vision example: How Phase 2 (Learning) + Phase 3 (Planning + Safety + Obs + LongHorizon) work together in Rust.
//! Updated to demonstrate FULL flow using runner entrypoint + all crates (2026 port).

use agentforge_learning::{TrajectoryDataset, DPOTrainer, SkillImprover, TrainingConfig, BaseTrainer};
use agentforge_long_horizon::LongTaskManager;
use agentforge_observability::{replay_trajectory_to_spans, Span};
// use agentforge_planning::HierarchicalPlanner;  // enabled when runner dev-deps include it or via workspace example config
use agentforge_runner::run_with_full_stack;
use agentforge_safety::create_default_policy_engine;

fn main() {
    println!("=== AgentForge Phase 2 + Phase 3 FULL Rust Flow Demo ===\n");

    // === Phase 2: Learning Flywheel (full) ===
    println!("[Phase 2] Building versioned high-quality dataset...");
    let mut dataset = TrajectoryDataset::new("phase2_3_vision_full");
    // Simulate adding real-like records (from eval JSONL in prod)
    // In real: load from Python eval/post_process outputs via serde_jsonl
    println!("   (In prod: populated via TrajectoryRecord from agentforge/eval + PRM)");

    println!("[Phase 2] Compute learning value + export preference pairs...");
    dataset.compute_learning_value();
    let pairs = dataset.export_preference_pairs();
    println!("   Preference pairs ready for DPO: {} (stub)", pairs.len());

    println!("[Phase 2] Proposing improved skill...");
    let improver = SkillImprover::new();
    let proposal = improver.propose_improvements("rust-port-phase3", &[], &[]);
    println!("   Rationale: {}", proposal.overall_rationale);

    println!("[Phase 2] Preparing via multiple trainers...");
    let trainer = DPOTrainer;
    let _p = trainer.prepare_dataset(&dataset, None).ok();
    let cfg = TrainingConfig::default();
    println!("   DPO/SFT/KTO dry-runs ready. Config lr={}", cfg.learning_rate);

    // === Phase 3: Full stack via runner (planning + safety + obs + prm spans) ===
    println!("\n[Phase 3] Invoking FULL STACK runner entrypoint (planning/safety/obs/learning)...");
    let stack_res = run_with_full_stack("Implement long-horizon checkpoints with topo safety gates", "grok");
    println!("   Runner outcome: {}", stack_res.outcome);
    println!("   Plan subtasks: {}", stack_res.plan.as_ref().map(|p| p.subtasks.len()).unwrap_or(0));
    println!("   Spans (with PRM): {}", stack_res.spans.len());
    if let Some(p) = stack_res.prm_overall { println!("   Overall PRM: {:.2}", p); }

    // Demo replay + OTEL shape
    let demo_events = vec![serde_json::json!({"type":"llm_turn"}), serde_json::json!({"type":"tool_result"})];
    let spans: Vec<Span> = replay_trajectory_to_spans("vision", &demo_events, Some(0.88));
    println!("   OTEL-like export sample keys: {}", spans[0].to_otel_like()["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["name"]);

    // === Long Horizon + Planning + Safety integration ===
    println!("\n[Long-Horizon] Start resumable task with checkpoints...");
    let mut lh = LongTaskManager::new();
    let ltask = lh.start_long_task("Port all 3 phases + PyO3 doc + tests to Rust", true);
    println!("   LongTask {} created with plan, checkpoint at {:?}", ltask.id, ltask.checkpoint_path);
    lh.heartbeat(&ltask.id, "Rust port 80% complete - tests+interop added", 0.8);
    println!("   Heartbeat updated + checkpointed.");

    println!("[Safety] Policy gate demo on long task subtask...");
    let policy = create_default_policy_engine();
    // (would pass to lh.execute_subtask_safely in real)
    let safe_dec = policy.evaluate("subtask_execution", &std::collections::HashMap::new());
    println!("   Default decision: {:?}", safe_dec.decision);

    println!("\n=== COMPLETE: Rust now has trainers+versioned-ds+learning_value | topo+checkpoint | long-horizon | enhanced-safety | real Span+replay+PRM+OTEL | runner bin + PyO3 doc + tests ===");
    println!("Next: cargo test ; exec from Python for dataset export wins.");
}
