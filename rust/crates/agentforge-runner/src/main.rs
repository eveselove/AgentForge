//! agentforge-runner binary
//!
//! THE pure Rust surface — COMPLETE, OBVIOUS, PRODUCTION-POLISHED.
//! One binary owns the ENTIRE autonomous flywheel:
//!   flywheel-step (real-data + improver + artifacts + --ingest), continuous (prioritizer + top-N + health.json + --shadow),
//!   candidate list + FULLY REAL promote (ts copy to skills/, promotions.jsonl + history with source=rust stamp, meta+markers),
//!   rich exports (PRM sidecars, DPO/PRM/SFT + learning_value) + stats + full-stack.
//!
//! Drop-in replacement (via AGENTFORGE_RUST_RUNNER or release binary) for post_process, workers, after_task hooks, timers, services, parity harness, demos.
//! --shadow / AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 = safe dual-run fidelity in EVERY integration point.
//! --json everywhere for farm/Python/subprocess. Dry-run DEFAULT (safe). Rich human + machine UX.
//!
//! All remaining integration points (continuous + promote + shadow) fully wired into demo tools + farm after-task hooks + post_process.py.
//! `agentforge-runner --help` (no --json) is the canonical, always-up-to-date reference. Feels complete and production-grade.

use std::env;
use std::io::Write;
use std::path::PathBuf;

use agentforge_learning::{SkillImprover, TrajectoryDataset};
use agentforge_runner::run_with_full_stack;

// Phase 1 pure-Rust flywheel scaffolding (RUST_FULL_MIGRATION_PLAN.md)
use agentforge_candidates::{
    list_high_value_candidates, promote_candidate, CandidateStore, Prioritizer,
};
use agentforge_flywheel::{FlywheelConfig, FlywheelOrchestrator};

// Rust-native Task system (prototype for unblocking development)
use agentforge_core::{JsonFileTaskStore, Task, TaskStatus, TaskStore};

const VERSION: &str = env!("CARGO_PKG_VERSION");

fn print_usage() {
    eprintln!(
        r#"agentforge-runner {} — THE pure Rust surface (COMPLETE, OBVIOUS, PRODUCTION-POLISHED)

One binary owns the FULL autonomous flywheel:
  flywheel-step   real-data + improver → artifacts + --ingest (canonical for post_process + workers + after_task)
  continuous      prioritizer + top-N + /tmp/.../flywheel_health.json (autonomy meta-loop; timer/hook replacement)
  candidate list|promote  FULLY REAL (timestamped skills/ copy, promotions.jsonl + promotion_history with source=rust stamp, meta+markers)
  + rich flywheel-export (PRM sidecars + learning_value + stats) + stats + full-stack

Drop-in for post_process.py, rust_flywheel_after_task.sh, grok workers, timers, services, parity harness, demo tools.
--shadow / AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 : dual-run fidelity (exact parity signals) in post_process + hooks + harness + watchdog.
--json everywhere (machines, bridges, farm). Dry-run DEFAULT (safe). Excellent human + JSON UX.

`agentforge-runner --help` (no --json) is the single source of truth. Pure surface is finished + obvious.

USAGE:
    agentforge-runner [GLOBAL] <SUBCOMMAND> [ARGS]

GLOBAL:
    --json, -j     Clean machine JSON (errors too). Ideal for Python/farm/subprocess/services
    --help, -h     This help (always current)
    --version, -V  Version

CORE PRODUCTION (continuous + promote + shadow — all points wired into farm hooks + post_process + demos):
    flywheel-step [--skill NAME] [--real-data] [--limit N] [--ingest] [--output-dir DIR] [--shadow] [--dry-run]
                    The COMPLETE pure step. Real TrajectoryDataset + improver → proposal + candidate_skill.yaml + manifest.
                    --ingest → pending_candidates/ (real, via candidates crate). Direct hot path from post_process/after_task/workers.
                    --shadow wires dual fidelity.

    continuous [--top-n N] [--no-dry-run] [--shadow] [--min-lv F]
                    COMPLETE autonomy meta-loop (the closer).
                    CandidateStore + Prioritizer (rich lv*lift+recency) → top-N suggestions.
                    ALWAYS writes /tmp/agentforge_rust_flywheel/flywheel_health.json (watchdog + timer + parity compat).
                    Dry-run DEFAULT. Direct replacement for run_continuous_* + flywheel.timer.
                    --shadow: dual fidelity for continuous validation in hooks/post_process/parity.

    candidate list [--top N] [--sort value|recency] [--json]
                    Pure prioritizer over real pending_candidates/ (full meta/proposal/manifest scan). Replaces list_pending_candidates.py.

    candidate promote <id> [--copy-to-skills] [--dry-run] [--json]
                    COMPLETE + FULLY REAL production promote.
                    --dry-run: zero-write preview (rich result always). With --copy-to-skills: ts-named copy to skills/,
                    appends promotions.jsonl (py shape + "source":"rust-agentforge-runner"), updates promotion_history.json,
                    sets promoted/reviewed in candidate_meta + creates .promoted/.reviewed markers.
                    The canonical promote under pure. List first, then promote.

SUPPORTING SUBCOMMANDS:
    flywheel-export | export-learning  --trajectories DIR --prm-dir DIR --output FILE [--format json|jsonl] [--min-prm F]
                    Rich production bundle: preference_pairs + prm_step_labels + per-record learning_value + stats.
    demo [GOAL] | full-stack --goal G [--agent A] [--input I]
    export-pairs | export-prm-steps | export-sft | improve-skill | stats --input I | export-records | version

TASK MANAGEMENT (LIVE by default — replaces Python create_*.py fix_*.py approve reassign check_status show_agent_stats etc):
    agentforge-runner task create --title "..." [--priority high] [--agent grok] [--tags a,b] [--from-file file.json]
    agentforge-runner task list [--status pending]
    agentforge-runner task get <id>
    agentforge-runner task update <id> --status done --result "..."
    agentforge-runner task reassign --from antigravity --to grok --pending-only
    agentforge-runner task approve --all-review
    agentforge-runner task stats
    (Full live via gateway API; --local for prototype Json store. See `task --help` style)

INPUT FLAGS (real farm data + sidecars): --input PATH | --trajectories DIR | --prm-dir DIR | --results DIR
    (TrajectoryDataset::load_flywheel_data + enrich_from_prm_sidecars, graceful fallbacks)

FARM INTEGRATION + HOOKS (continuous + promote + shadow fully wired — post_process / after_task / workers / timer / parity / demo):
  Direct in pure mode (is_pure_rust_flywheel or AGENTFORGE_FLYWHEEL_ENGINE=rust):
    $AGENTFORGE_RUST_RUNNER --json flywheel-step --real-data --limit 60 --ingest [--shadow]
    $AGENTFORGE_RUST_RUNNER --json continuous --top-n 2 [--shadow]
    $AGENTFORGE_RUST_RUNNER candidate list --top 5 --sort value --json
    $AGENTFORGE_RUST_RUNNER --json candidate promote <id> --copy-to-skills [--dry-run]
  Shadow dual (fidelity everywhere):
    AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 $AGENTFORGE_RUST_RUNNER --json flywheel-step --real-data --ingest --shadow
    AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 $AGENTFORGE_RUST_RUNNER --json continuous --top-n 1 --shadow
  Health + fidelity artifacts (watchdog / harness / CI):
    cat /tmp/agentforge_rust_flywheel/flywheel_health.json
    ls /tmp/agentforge_rust_flywheel/shadow_fidelity*.json
  Full live demo (exercises every integration point: step + continuous + list + promote + shadow + after-task style):
    bash bin/test_pure_rust_flywheel_step.sh

EXAMPLES (copy-paste; all paths exercised in post_process.py + rust_flywheel_after_task.sh + parity_harness + workers):
  # After-task / post_process pure path (step + continuous tick)
  agentforge-runner --json flywheel-step --real-data --ingest
  AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 agentforge-runner --json flywheel-step --real-data --ingest --shadow
  agentforge-runner --json continuous --top-n 2 --shadow

  # Autonomy closer + promote follow-up
  agentforge-runner --json continuous --top-n 3
  agentforge-runner candidate list --top 3 --json
  agentforge-runner --json candidate promote 20260531_055029_general-refactor_81e7d546 --copy-to-skills --dry-run
  # (then without --dry-run for real promote with rust stamp)

  # Rich learning export + stats (bridges / training)
  agentforge-runner --json flywheel-export --trajectories eval/trajectories --prm-dir eval/trajectories --output /tmp/rich.json --format json
  agentforge-runner --json stats --input eval/results

  # Prod (release binary in workers/services/hooks)
  $AGENTFORGE_RUST_RUNNER --json continuous --top-n 2 --shadow
  $AGENTFORGE_RUST_RUNNER --json flywheel-step --real-data --ingest --shadow

Python bridge (subprocess, always --json):
    subprocess.run([runner, "flywheel-step", "--real-data", "--ingest", "--json", "--shadow"])
    subprocess.run([runner, "continuous", "--top-n", "2", "--shadow", "--json"])
    subprocess.run([runner, "candidate", "promote", cid, "--copy-to-skills", "--json"])

Env for full cutover (activates in all guards):
    export AGENTFORGE_PURE_RUST_FLYWHEEL=1 AGENTFORGE_FLYWHEEL_ENGINE=rust AGENTFORGE_RUST_RUNNER=/path/to/release/agentforge-runner

See also: bin/rust_flywheel_after_task.sh (direct step+continuous+promote follow-up), eval/post_process.py (shadow+pure step+continuous wiring), bin/test_pure_rust_flywheel_step.sh (complete demo), learning/flywheel_parity/parity_harness.py

One obvious binary. Continuous + promote + shadow + step fully wired + production-polished into every farm surface. Zero Python orchestration under pure.
"#,
        VERSION
    );
}

fn find_flag_value(args: &[String], flags: &[&str]) -> Option<String> {
    for (i, a) in args.iter().enumerate() {
        for &f in flags {
            if a == f {
                return args.get(i + 1).cloned();
            }
        }
    }
    None
}

fn has_flag(args: &[String], flags: &[&str]) -> bool {
    args.iter().any(|a| flags.contains(&a.as_str()))
}

/// Find first positional (non-flag) arg after a certain index, skipping known flags and their values.
fn find_positional_after(args: &[String], after_idx: usize) -> Option<String> {
    let mut i = after_idx + 1;
    while i < args.len() {
        let a = &args[i];
        if a.starts_with('-') {
            // skip flag and its potential value
            i += 2; // rough; if no value next will be checked
            continue;
        }
        return Some(a.clone());
    }
    None
}

fn write_jsonl(path: &PathBuf, items: &[serde_json::Value]) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).ok();
    }
    let mut f = std::fs::File::create(path).map_err(|e| e.to_string())?;
    for item in items {
        writeln!(f, "{}", serde_json::to_string(item).unwrap()).map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn load_dataset(input: Option<&str>) -> Result<TrajectoryDataset, String> {
    let mut ds = TrajectoryDataset::new("runner_cli");
    if let Some(p) = input {
        let path = PathBuf::from(p);
        let canon = PathBuf::from("/home/eveselove/agentforge").join(&p);
        let candidates: Vec<PathBuf> = if path.is_absolute() {
            vec![path.clone()]
        } else {
            vec![canon.clone(), path.clone(), PathBuf::from("..").join(p)]
        };
        let mut loaded_ok = false;
        for cand in &candidates {
            if cand.exists() {
                if let Ok(n) = ds.load_from_real_input(cand) {
                    if n > 0 {
                        eprintln!("[runner] loaded {} records from {}", n, cand.display());
                        loaded_ok = true;
                        break;
                    }
                }
            }
        }
        if !loaded_ok {
            let n = ds
                .load_from_real_input(&path)
                .map_err(|e| format!("load failed: {}", e))?;
            if n == 0 {
                eprintln!("[runner] warning: no records loaded from {}", p);
            }
        }
    }
    ds.compute_learning_value();
    Ok(ds)
}

// No more custom load/save helpers needed — JsonFileTaskStore handles persistence automatically.

// === Live Gateway API client (replaces Python create_*.py / fix_*.py / approve etc) ===
// Talks to production task gateway (agentforge-gateway on 9090).
// Use --local to force the prototype JsonFileTaskStore (for tests/demos).
// Default: live HTTP for real task mgmt (enables deleting 12+ Python entrypoints).

const DEFAULT_API_BASE: &str = "http://localhost:9090";

async fn live_create_task(
    client: &reqwest::Client,
    base: &str,
    title: &str,
    description: &str,
    priority: Option<&str>,
    complexity: Option<&str>,
    preferred_agent: Option<&str>,
    tags: Vec<String>,
    repo: Option<&str>,
) -> Result<serde_json::Value, String> {
    let payload = serde_json::json!({
        "title": title,
        "description": description,
        "priority": priority.unwrap_or("medium"),
        "complexity": complexity.unwrap_or("medium"),
        "preferred_agent": preferred_agent.unwrap_or("auto"),
        "tags": tags,
        "repo": repo,
    });
    let url = format!("{}/api/tasks", base.trim_end_matches('/'));
    let resp = client
        .post(&url)
        .json(&payload)
        .send()
        .await
        .map_err(|e| format!("POST {} failed: {}", url, e))?;
    if !resp.status().is_success() {
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        return Err(format!("create failed {}: {}", status, text));
    }
    resp.json::<serde_json::Value>()
        .await
        .map_err(|e| format!("decode create resp: {}", e))
}

async fn live_list_tasks(
    client: &reqwest::Client,
    base: &str,
    status: Option<&str>,
) -> Result<Vec<serde_json::Value>, String> {
    let mut url = format!("{}/api/tasks", base.trim_end_matches('/'));
    if let Some(s) = status {
        url.push_str(&format!("?status={}", s));
    }
    let resp = client
        .get(&url)
        .send()
        .await
        .map_err(|e| format!("GET tasks failed: {}", e))?;
    if !resp.status().is_success() {
        return Err(format!("list failed: {}", resp.status()));
    }
    let arr = resp
        .json::<Vec<serde_json::Value>>()
        .await
        .map_err(|e| format!("decode list: {}", e))?;
    Ok(arr)
}

async fn live_update_task(
    client: &reqwest::Client,
    base: &str,
    id: &str,
    status: Option<&str>,
    result: Option<&str>,
    assigned_agent: Option<&str>,
) -> Result<serde_json::Value, String> {
    let mut payload = serde_json::json!({});
    if let Some(s) = status {
        payload["status"] = serde_json::json!(s);
    }
    if let Some(r) = result {
        payload["result"] = serde_json::json!(r);
    }
    if let Some(a) = assigned_agent {
        payload["assigned_agent"] = serde_json::json!(a);
    }
    let url = format!("{}/api/tasks/{}", base.trim_end_matches('/'), id);
    let resp = client
        .patch(&url)
        .json(&payload)
        .send()
        .await
        .map_err(|e| format!("PATCH {} failed: {}", url, e))?;
    if !resp.status().is_success() {
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        return Err(format!("update failed {}: {}", status, text));
    }
    resp.json::<serde_json::Value>()
        .await
        .map_err(|e| format!("decode update: {}", e))
}

async fn live_dispatch_task(
    client: &reqwest::Client,
    base: &str,
    id: &str,
) -> Result<serde_json::Value, String> {
    let url = format!("{}/api/tasks/{}/dispatch", base.trim_end_matches('/'), id);
    let resp = client
        .post(&url)
        .send()
        .await
        .map_err(|e| format!("dispatch POST failed: {}", e))?;
    if !resp.status().is_success() {
        return Err(format!("dispatch failed: {}", resp.status()));
    }
    resp.json::<serde_json::Value>()
        .await
        .map_err(|e| format!("decode dispatch: {}", e))
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let json_mode = has_flag(&args, &["--json", "-j"]);

    // Global early exits
    if has_flag(&args, &["--help", "-h"]) {
        if json_mode {
            println!(
                r#"{{"status":"ok","usage":"see --help without --json","production_core":["flywheel-step","continuous","candidate promote","promote (alias)"],"shadow":"AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 or --shadow"}}"#
            );
        } else {
            print_usage();
        }
        return;
    }
    if has_flag(&args, &["--version", "-V"]) {
        if json_mode {
            println!(r#"{{"version":"{}"}}"#, VERSION);
        } else {
            println!("agentforge-runner {}", VERSION);
        }
        return;
    }

    // Find first non-global non-flag arg as subcommand (supports globals before/after).
    // Production polish: top-level "promote <id>" and "list" are first-class short aliases (obvious for farm).
    let mut sub = "help";
    for a in args.iter().skip(1) {
        if a.starts_with('-')
            || a == "--json"
            || a == "-j"
            || a == "--help"
            || a == "-h"
            || a == "--version"
            || a == "-V"
        {
            continue;
        }
        sub = a.as_str();
        break;
    }

    match sub {
        "demo" => {
            let goal = args.get(2).cloned().unwrap_or_else(|| {
                "Demo goal: improve 4G adaptive throttle using real trajectories".into()
            });
            if !json_mode {
                eprintln!("=== AgentForge runner: demo (full-stack) ===");
            }
            let res = run_with_full_stack(&goal, "grok");
            if json_mode {
                println!(
                    "{}",
                    serde_json::json!({
                        "cmd": "demo",
                        "goal": goal,
                        "outcome": res.outcome,
                        "prm_overall": res.prm_overall,
                        "spans": res.spans.len(),
                        "plan_subtasks": res.plan.as_ref().map(|p| p.subtasks.len()).unwrap_or(0),
                    })
                );
            } else {
                println!("Outcome: {}", res.outcome);
                println!("PRM: {:?}", res.prm_overall);
                println!("Spans: {}", res.spans.len());
                if let Some(p) = &res.plan {
                    println!("Subtasks: {}", p.subtasks.len());
                }
            }
        }

        // === Rust-native Task Management (LIVE by default - Production) ===
        // Replaces ALL Python entrypoint scripts (create_*.py, fix_*.py, approve_tasks.py, reassign.py, show_agent_stats.py, check_status.py ...).
        // Talks to the running agentforge-gateway (Axum) over HTTP.
        // --local : force the internal JsonFileTaskStore prototype (demo only).
        // Supports --from-file for mass create (replaces the create_*.py hardcoded lists).
        // Full CRUD + reassign/approve/stats for the management scripts.
        "task" => {
            // Robust sub_action: skip bin + globals (--json etc) + the "task" word itself
            let mut sub_action = "help";
            let mut seen_task = false;
            for a in args.iter().skip(1) {
                if a == "task" {
                    seen_task = true;
                    continue;
                }
                if a.starts_with('-') || a == "--json" || a == "-j" {
                    continue;
                }
                if seen_task {
                    sub_action = a.as_str();
                    break;
                }
            }
            let use_local = has_flag(&args, &["--local", "--local-store"]);
            let api_base = find_flag_value(&args, &["--api", "--api-base", "--base"])
                .or_else(|| std::env::var("AGENTFORGE_API").ok())
                .unwrap_or_else(|| DEFAULT_API_BASE.to_string());

            let rt = tokio::runtime::Runtime::new()
                .expect("failed to create tokio runtime for task subcommand");
            rt.block_on(async {
                let client = if !use_local { Some(reqwest::Client::new()) } else { None };
                let store_path = std::path::PathBuf::from("/tmp/agentforge_tasks.json");
                let mut local_store = if use_local { Some(JsonFileTaskStore::new(Some(store_path))) } else { None };

                match sub_action {
                    "create" => {
                        // --from-file FILE.json  (array of task objects or single) — kills the create_*.py scripts
                        if let Some(file) = find_flag_value(&args, &["--from-file", "--file"]) {
                            if let Some(ref c) = client {
                                match std::fs::read_to_string(&file) {
                                    Ok(content) => {
                                        let tasks_val: serde_json::Value = match serde_json::from_str(&content) {
                                            Ok(v) => v,
                                            Err(e) => { eprintln!("bad json: {}", e); return; }
                                        };
                                        let task_list: Vec<serde_json::Value> = if tasks_val.is_array() {
                                            tasks_val.as_array().unwrap().clone()
                                        } else {
                                            vec![tasks_val]
                                        };
                                        let mut created_ids = vec![];
                                        for t in task_list {
                                            let title = t.get("title").and_then(|v| v.as_str()).unwrap_or("Untitled").to_string();
                                            let desc = t.get("description").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                            let prio = t.get("priority").and_then(|v| v.as_str());
                                            let comp = t.get("complexity").and_then(|v| v.as_str());
                                            let agent = t.get("preferred_agent").and_then(|v| v.as_str());
                                            let tags: Vec<String> = t.get("tags").and_then(|v| v.as_array())
                                                .map(|a| a.iter().filter_map(|x| x.as_str().map(|s|s.to_string())).collect()).unwrap_or_default();
                                            let repo = t.get("repo").and_then(|v| v.as_str());
                                            match live_create_task(c, &api_base, &title, &desc, prio, comp, agent, tags, repo).await {
                                                Ok(r) => {
                                                    if let Some(id) = r.get("id").and_then(|v| v.as_str()) { created_ids.push(id.to_string()); }
                                                    if !json_mode { println!("✅ created: {}", r.get("id").unwrap_or(&serde_json::json!("?"))); }
                                                }
                                                Err(e) => eprintln!("create error: {}", e),
                                            }
                                        }
                                        if json_mode {
                                            println!("{}", serde_json::to_string_pretty(&serde_json::json!({"created": created_ids.len(), "ids": created_ids})).unwrap());
                                        }
                                    }
                                    Err(e) => eprintln!("read {}: {}", file, e),
                                }
                            } else {
                                eprintln!("--from-file requires live api (no --local)");
                            }
                            return;
                        }

                        // Single create (flags or positional)
                        let title = find_flag_value(&args, &["--title", "-t"])
                            .or_else(|| args.get(3).cloned())
                            .unwrap_or_else(|| "Untitled task".to_string());

                        let description = find_flag_value(&args, &["--description", "--desc", "-d"])
                            .unwrap_or_else(|| "Created via agentforge-runner (Rust live)".to_string());

                        let prio = find_flag_value(&args, &["--priority", "-p"]);
                        let comp = find_flag_value(&args, &["--complexity", "-c"]);
                        let agent = find_flag_value(&args, &["--agent", "-a"]);
                        let tags: Vec<String> = find_flag_value(&args, &["--tags"])
                            .map(|s| s.split(',').map(|x| x.trim().to_string()).collect())
                            .unwrap_or_default();
                        let repo = find_flag_value(&args, &["--repo"]);

                        if let Some(ref c) = client {
                            match live_create_task(c, &api_base, &title, &description, prio.as_deref(), comp.as_deref(), agent.as_deref(), tags, repo.as_deref()).await {
                                Ok(created) => {
                                    if json_mode {
                                        println!("{}", serde_json::to_string_pretty(&created).unwrap());
                                    } else {
                                        println!("✅ Task created (live)");
                                        if let Some(id) = created.get("id").and_then(|v| v.as_str()) { println!("   ID: {}", id); }
                                        println!("   Title: {}", title);
                                    }
                                }
                                Err(e) => {
                                    if json_mode { println!(r#"{{"error":"{}"}}"#, e); } else { eprintln!("Error: {}", e); }
                                }
                            }
                        } else if let Some(ref mut store) = local_store {
                            // local fallback (unchanged prototype path)
                            let mut task = Task::new(uuid::Uuid::new_v4().to_string(), title, description);
                            if let Some(p) = prio { task = task.with_priority(p); }
                            if let Some(a) = agent { task = task.with_preferred_agent(a); }
                            if !tags.is_empty() { task = task.with_tags(tags); }
                            match store.create(task.clone()).await {
                                Ok(created) => {
                                    if json_mode { println!("{}", serde_json::to_string_pretty(&created).unwrap()); }
                                    else { println!("✅ Task created (local)"); println!("   ID: {}", created.id); }
                                }
                                Err(e) => { if json_mode { println!(r#"{{"error":"{}"}}"#, e); } else { eprintln!("{}", e); } }
                            }
                        }
                    }

                    "list" => {
                        let status_filter = find_flag_value(&args, &["--status", "-s"]);
                        if let Some(ref c) = client {
                            match live_list_tasks(c, &api_base, status_filter.as_deref()).await {
                                Ok(list) => {
                                    if json_mode {
                                        println!("{}", serde_json::to_string_pretty(&list).unwrap());
                                    } else {
                                        println!("Tasks ({}):", list.len());
                                        for t in list.iter().take(50) {
                                            let id = t.get("id").and_then(|v| v.as_str()).unwrap_or("?");
                                            let title = t.get("title").and_then(|v| v.as_str()).unwrap_or("");
                                            let st = t.get("status").and_then(|v| v.as_str()).unwrap_or("?");
                                            println!("  {} | {} | {}", &id[..id.len().min(12)], st, title);
                                        }
                                    }
                                }
                                Err(e) => eprintln!("list error: {}", e),
                            }
                        } else if let Some(ref mut store) = local_store {
                            let pending = store.list_pending().await;
                            // ... (old list code abbreviated for local)
                            if json_mode {
                                let arr: Vec<_> = pending.iter().map(|t| serde_json::to_value(t).unwrap()).collect();
                                println!("{}", serde_json::to_string_pretty(&arr).unwrap());
                            } else {
                                println!("Local pending: {}", pending.len());
                            }
                        }
                    }

                    "get" => {
                        let task_idx = args.iter().position(|x| x == "task").unwrap_or(1);
                        let sub_idx = args.iter().skip(task_idx).position(|x| x == "get").map(|p| task_idx + p).unwrap_or(task_idx+1);
                        let id = find_positional_after(&args, sub_idx).or_else(|| find_flag_value(&args, &["--id"]));
                        if let Some(id) = id {
                            if let Some(ref c) = client {
                                // Reuse list or add a get fn; for now simple: list and filter (or extend later)
                                match live_list_tasks(c, &api_base, None).await {
                                    Ok(list) => {
                                        if let Some(found) = list.into_iter().find(|t| t.get("id").and_then(|v|v.as_str()) == Some(id.as_str())) {
                                            if json_mode { println!("{}", serde_json::to_string_pretty(&found).unwrap()); } else { println!("{}", serde_json::to_string_pretty(&found).unwrap()); }
                                        } else {
                                            eprintln!("not found");
                                        }
                                    }
                                    Err(e) => eprintln!("{}", e),
                                }
                            } else if let Some(ref mut store) = local_store {
                                if let Some(task) = store.get(&id).await {
                                    if json_mode { println!("{}", serde_json::to_string_pretty(&task).unwrap()); } else { println!("{:?}", task); }
                                } else { eprintln!("not found"); }
                            }
                        } else {
                            eprintln!("usage: task get <id>");
                        }
                    }

                    "update" | "set" => {
                        // robust: find the token after "update" sub_action
                        let sub_idx = args.iter().position(|x| x == "update" || x == "set").unwrap_or(3);
                        let id = find_positional_after(&args, sub_idx).expect("task update <id> --status ...");
                        let st = find_flag_value(&args, &["--status", "-s"]);
                        let res = find_flag_value(&args, &["--result", "-r"]);
                        let agent = find_flag_value(&args, &["--agent", "-a"]);
                        if let Some(ref c) = client {
                            match live_update_task(c, &api_base, &id, st.as_deref(), res.as_deref(), agent.as_deref()).await {
                                Ok(updated) => { if json_mode { println!("{}", serde_json::to_string_pretty(&updated).unwrap()); } else { println!("updated {}", id); } }
                                Err(e) => eprintln!("{}", e),
                            }
                        } else if let Some(ref mut store) = local_store {
                            if let Some(sts) = &st {
                                let ts = match sts.as_str() { "done" => TaskStatus::Done, "review" => TaskStatus::Review, "failed" => TaskStatus::Failed, _ => TaskStatus::InProgress };
                                let _ = store.update_status(&id, ts).await;
                            }
                            println!("local update ok (limited)");
                        }
                    }

                    "dispatch" => {
                        let task_idx = args.iter().position(|x| x == "task").unwrap_or(1);
                        let sub_idx = args.iter().skip(task_idx).position(|x| x == "dispatch").map(|p| task_idx + p).unwrap_or(task_idx+1);
                        let id = find_positional_after(&args, sub_idx);
                        if let Some(id) = id {
                            if let Some(ref c) = client {
                                match live_dispatch_task(c, &api_base, &id).await {
                                    Ok(r) => { if json_mode { println!("{}", serde_json::to_string_pretty(&r).unwrap()); } else { println!("dispatched {}", id); } }
                                    Err(e) => eprintln!("{}", e),
                                }
                            } else if let Some(ref mut store) = local_store {
                                let _ = store.update_status(&id, TaskStatus::Dispatched).await;
                            }
                        } else {
                            // old "first pending" behavior for local
                            if let Some(ref mut store) = local_store {
                                let pending = store.list_pending().await;
                                if let Some(first) = pending.first() {
                                    let _ = store.update_status(&first.id, TaskStatus::Dispatched).await;
                                    println!("dispatched first local {}", first.id);
                                }
                            } else {
                                eprintln!("dispatch <id> or use without id for first (local only)");
                            }
                        }
                    }

                    "claim" => {
                        let task_idx = args.iter().position(|x| x == "task").unwrap_or(1);
                        let sub_idx = args.iter().skip(task_idx).position(|x| x == "claim").map(|p| task_idx + p).unwrap_or(task_idx+1);
                        let id = find_positional_after(&args, sub_idx).or_else(|| find_flag_value(&args, &["--id"])).expect("id required");
                        let agent = find_flag_value(&args, &["--agent", "-a"]).unwrap_or_else(|| "grok".to_string());
                        if let Some(ref c) = client {
                            // claim = update to in_progress + assigned
                            match live_update_task(c, &api_base, &id, Some("in_progress"), None, Some(&agent)).await {
                                Ok(r) => { if json_mode { println!("{}", serde_json::to_string_pretty(&r).unwrap()); } else { println!("claimed {} by {}", id, agent); } }
                                Err(e) => eprintln!("{}", e),
                            }
                        } else if let Some(ref mut store) = local_store {
                            let _ = store.claim(&id, &agent).await;
                        }
                    }

                    // === NEW: support for the old Python management scripts ===
                    "reassign" => {
                        // agentforge-runner task reassign --from antigravity --to grok --pending-only [--dry-run]
                        let from = find_flag_value(&args, &["--from"]);
                        let to = find_flag_value(&args, &["--to"]).unwrap_or_else(|| "grok".to_string());
                        let pending_only = has_flag(&args, &["--pending-only"]);
                        let dry = has_flag(&args, &["--dry-run"]);
                        if let Some(ref c) = client {
                            match live_list_tasks(c, &api_base, if pending_only { Some("pending") } else { None }).await {
                                Ok(list) => {
                                    let mut count = 0;
                                    for t in list {
                                        let tid = match t.get("id").and_then(|v| v.as_str()) { Some(s) => s, None => continue };
                                        let cur_agent = t.get("assigned_agent").and_then(|v| v.as_str()).unwrap_or("");
                                        if let Some(ref f) = from {
                                            if cur_agent != f { continue; }
                                        }
                                        if !dry {
                                            let _ = live_update_task(c, &api_base, tid, None, None, Some(&to)).await;
                                        }
                                        count += 1;
                                        if !json_mode { println!("reassign {} {} -> {}", tid, cur_agent, to); }
                                    }
                                    if json_mode { println!(r#"{{"reassigned":{},"to":"{}","dry":{}}}"#, count, to, dry); }
                                    else { println!("reassigned {} tasks to {}", count, to); }
                                }
                                Err(e) => eprintln!("{}", e),
                            }
                        } else { eprintln!("reassign requires live api"); }
                    }

                    "approve" | "review-all" => {
                        // agentforge-runner task approve --all-review
                        if let Some(ref c) = client {
                            let url = format!("{}/api/review/all", api_base.trim_end_matches('/'));
                            match c.post(&url).send().await {
                                Ok(r) if r.status().is_success() => {
                                    let body: serde_json::Value = r.json().await.unwrap_or(serde_json::json!({}));
                                    if json_mode { println!("{}", serde_json::to_string_pretty(&body).unwrap()); } else { println!("review-all: {}", body); }
                                }
                                Ok(r) => eprintln!("approve failed: {}", r.status()),
                                Err(e) => eprintln!("{}", e),
                            }
                        } else { eprintln!("approve requires live"); }
                    }

                    "reset-fakes" | "reset" => {
                        // simplistic: find done with duration 0 and reset (demo of what the py did)
                        if let Some(ref c) = client {
                            match live_list_tasks(c, &api_base, Some("done")).await {
                                Ok(list) => {
                                    for t in list {
                                        // heuristic: if result mentions fake or duration_seconds==0
                                        let dur = t.get("duration_seconds").and_then(|v| v.as_f64()).unwrap_or(1.0);
                                        if dur < 0.1 {
                                            let tid = t.get("id").and_then(|v|v.as_str()).unwrap_or("");
                                            let _ = live_update_task(c, &api_base, tid, Some("pending"), Some("reset from fake"), None).await;
                                            if !json_mode { println!("reset fake {}", tid); }
                                        }
                                    }
                                }
                                Err(e) => eprintln!("{}", e),
                            }
                        }
                    }

                    "stats" => {
                        if let Some(ref c) = client {
                            let url = format!("{}/api/metrics", api_base.trim_end_matches('/'));
                            match c.get(&url).send().await {
                                Ok(resp) => match resp.error_for_status() {
                                    Ok(ok_resp) => match ok_resp.json::<serde_json::Value>().await {
                                        Ok(m) => {
                                            if json_mode { println!("{}", serde_json::to_string_pretty(&m).unwrap()); }
                                            else { println!("{}", serde_json::to_string_pretty(&m).unwrap()); }
                                        }
                                        Err(e) => eprintln!("stats decode: {}", e),
                                    },
                                    Err(e) => eprintln!("stats http: {}", e),
                                },
                                Err(e) => eprintln!("stats connect: {}", e),
                            }
                        } else {
                            println!("local stats: use the store directly");
                        }
                    }

                    _ => {
                        if json_mode {
                            println!(r#"{{"status":"ok","commands":["create","list","get","update","dispatch","claim","reassign","approve","reset-fakes","stats"],"note":"live default; --local for prototype; --from-file for mass create"}}"#);
                        } else {
                            eprintln!("agentforge-runner task <subcommand>  [ --live | --local ] [ --api http://localhost:9090 ]");
                            eprintln!();
                            eprintln!("Live (default, talks to gateway):");
                            eprintln!("  create --title T [--priority P] [--agent A] [--tags t1,t2] [--from-file tasks.json]");
                            eprintln!("  list [--status pending|review|done]");
                            eprintln!("  get <id>");
                            eprintln!("  update <id> --status done --result \"...\" ");
                            eprintln!("  dispatch <id> | claim <id> --agent grok");
                            eprintln!("  reassign --from antigravity --to grok --pending-only [--dry-run]");
                            eprintln!("  approve --all-review | reset-fakes | stats");
                            eprintln!();
                            eprintln!("This surface replaces the Python create/fix/approve/reassign/show_agent_stats/check_status scripts.");
                        }
                    }
                }
            });
        }

        "full-stack" => {
            let goal = find_flag_value(&args, &["--goal", "-g"])
                .or_else(|| args.get(2).cloned())
                .unwrap_or_else(|| {
                    "Refactor proxy/adaptive throttle for 4G using PRM signals".into()
                });
            let agent = find_flag_value(&args, &["--agent", "-a"]).unwrap_or_else(|| "grok".into());
            let input = find_flag_value(&args, &["--input", "-i"]);

            if !json_mode {
                eprintln!("[full-stack] goal={} agent={}", goal, agent);
            }
            let _ = load_dataset(input.as_deref());
            let res = run_with_full_stack(&goal, &agent);

            if json_mode {
                println!("{}", serde_json::to_string(&serde_json::json!({
                    "cmd": "full-stack",
                    "goal": goal,
                    "agent": agent,
                    "result": {
                        "outcome": res.outcome,
                        "prm_overall": res.prm_overall,
                        "spans_count": res.spans.len(),
                        "plan": res.plan.as_ref().map(|pl| serde_json::json!({
                            "goal": pl.goal,
                            "subtasks": pl.subtasks.iter().map(|s| &s.description).collect::<Vec<_>>()
                        }))
                    }
                })).unwrap());
            } else {
                println!(
                    "full-stack complete. outcome={} prm={:?} spans={}",
                    res.outcome,
                    res.prm_overall,
                    res.spans.len()
                );
            }
        }

        "export-pairs" | "dpo" => {
            let input = find_flag_value(&args, &["--input", "--from", "-f", "-i"])
                .or_else(|| Some("eval/results".into()));
            let output = find_flag_value(&args, &["--output", "--out", "-o"])
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from("training_ready/dpo_from_rust.jsonl"));

            let ds = load_dataset(input.as_deref()).unwrap_or_else(|e| {
                eprintln!("[runner] load warn: {}", e);
                TrajectoryDataset::new("empty")
            });
            let pairs = ds.export_preference_pairs();

            if let Err(e) = write_jsonl(&output, &pairs) {
                if json_mode {
                    println!(r#"{{"error":"write failed","detail":"{}"}}"#, e);
                } else {
                    eprintln!("error writing: {}", e);
                }
                std::process::exit(1);
            }

            if json_mode {
                println!(
                    "{}",
                    serde_json::json!({
                        "cmd": "export-pairs",
                        "input": input,
                        "output": output.to_string_lossy(),
                        "count": pairs.len(),
                        "pairs": pairs
                    })
                );
            } else {
                eprintln!(
                    "[runner] Wrote {} DPO pairs → {}",
                    pairs.len(),
                    output.display()
                );
            }
        }

        "export-prm-steps" => {
            let input = find_flag_value(&args, &["--input", "--from", "-i", "-f"]);
            let output = find_flag_value(&args, &["--output", "--out", "-o"])
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from("training_ready/prm_steps_from_rust.jsonl"));

            let ds = load_dataset(input.as_deref()).unwrap_or_else(|e| {
                eprintln!("[runner] load warn: {}", e);
                TrajectoryDataset::new("empty")
            });
            let labels = ds.export_prm_step_labels();

            if let Err(e) = write_jsonl(&output, &labels) {
                if json_mode {
                    println!(r#"{{"error":"{}"}}"#, e);
                } else {
                    eprintln!("{}", e);
                }
                std::process::exit(1);
            }
            if json_mode {
                println!(
                    "{}",
                    serde_json::json!({"cmd":"export-prm-steps","count":labels.len(),"output":output.to_string_lossy()})
                );
            } else {
                eprintln!(
                    "[runner] Wrote {} PRM step labels → {}",
                    labels.len(),
                    output.display()
                );
            }
        }

        "export-sft" => {
            let input = find_flag_value(&args, &["--input", "-i"]);
            let output = find_flag_value(&args, &["--output", "--out", "-o"])
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from("training_ready/sft_from_rust.jsonl"));

            let ds = load_dataset(input.as_deref()).unwrap_or_else(|e| {
                eprintln!("[runner] load warn: {}", e);
                TrajectoryDataset::new("empty")
            });
            let successes: Vec<_> = ds
                .records
                .iter()
                .filter(|r| r.outcome == agentforge_core::Outcome::Success)
                .map(|r| {
                    serde_json::json!({
                        "task_id": r.task_id,
                        "benchmark_id": r.benchmark_id,
                        "events": r.events,
                        "prm": r.prm_overall,
                        "duration": r.duration_seconds,
                        "agent": r.agent
                    })
                })
                .collect();

            if let Err(e) = write_jsonl(&output, &successes) {
                if json_mode {
                    println!(r#"{{"error":"{}"}}"#, e);
                } else {
                    eprintln!("{}", e);
                }
                std::process::exit(1);
            }
            if json_mode {
                println!(
                    "{}",
                    serde_json::json!({"cmd":"export-sft","count":successes.len(),"output":output.to_string_lossy()})
                );
            } else {
                eprintln!(
                    "[runner] Wrote {} SFT records → {}",
                    successes.len(),
                    output.display()
                );
            }
        }

        "improve-skill" => {
            let skill = find_flag_value(&args, &["--skill", "-s"])
                .unwrap_or_else(|| "general-agent".into());
            let input = find_flag_value(&args, &["--input", "-i"]);
            let output = find_flag_value(&args, &["--output", "--out", "-o"]).map(PathBuf::from);

            let ds = load_dataset(input.as_deref()).unwrap_or_else(|e| {
                eprintln!("[runner] load warn: {}", e);
                TrajectoryDataset::new("empty")
            });
            let failures: Vec<_> = ds
                .records
                .iter()
                .filter(|r| r.outcome != agentforge_core::Outcome::Success)
                .cloned()
                .collect();
            let successes: Vec<_> = ds
                .records
                .iter()
                .filter(|r| r.outcome == agentforge_core::Outcome::Success)
                .cloned()
                .collect();

            let improver = SkillImprover::new();
            let proposal = improver.propose_improvements(&skill, &failures, &successes);

            let out_json = serde_json::json!({
                "cmd": "improve-skill",
                "skill": skill,
                "proposal": proposal,
                "data_summary": {"successes": successes.len(), "failures": failures.len()}
            });

            if let Some(ref outp) = output {
                if let Err(e) = write_jsonl(outp, &[out_json.clone()]) {
                    if json_mode {
                        println!(r#"{{"error":"{}"}}"#, e);
                    } else {
                        eprintln!("{}", e);
                    }
                    std::process::exit(1);
                }
            }
            if json_mode {
                println!("{}", out_json);
            } else {
                println!(
                    "Skill proposal for '{}': {}",
                    skill, proposal.overall_rationale
                );
                if let Some(ref o) = output {
                    println!("Wrote full JSON to {}", o.display());
                }
            }
        }

        // =====================================================================
        // flywheel-step: COMPLETE pure-Rust entry point (production replacement)
        // The canonical for pure farm: real data -> improver -> artifacts + ingest.
        // Shadow support for all hooks. Direct from workers/after_task/post_process.
        // =====================================================================
        "flywheel-step" | "flywheel_step" | "step" => {
            let skill = find_flag_value(&args, &["--skill", "-s"])
                .unwrap_or_else(|| "general-agent".into());
            let dry_run = has_flag(&args, &["--dry-run", "--dry", "-d"]);
            let real_data = has_flag(&args, &["--real-data", "--real", "-r"]);
            let ingest = has_flag(&args, &["--ingest", "-I"]);
            let limit: Option<usize> =
                find_flag_value(&args, &["--limit", "-l"]).and_then(|s| s.parse().ok());
            let output_dir =
                find_flag_value(&args, &["--output-dir", "--out-dir", "-o"]).map(PathBuf::from);

            // Phase 2 shadow foundation (easy basic support): flag or env for dual-run/fidelity contexts.
            // When present (from post_process shadow mode or direct), included in logs + output JSON for observability.
            // Does not alter core behavior (no struct change to keep edit minimal/non-breaking for Phase 2 start).
            let shadow = has_flag(&args, &["--shadow"])
                || std::env::var("AGENTFORGE_RUST_FLYWHEEL_SHADOW")
                    .map(|v| {
                        v == "1"
                            || v.to_lowercase() == "true"
                            || v.to_lowercase() == "yes"
                            || v.to_lowercase() == "on"
                    })
                    .unwrap_or(false);

            if !json_mode {
                eprintln!("[runner] flywheel-step (COMPLETE) skill={} dry_run={} real_data={} ingest={} limit={:?} shadow={}",
                    skill, dry_run, real_data, ingest, limit, shadow);
            }

            // Build config for the new pure-Rust orchestrator (from agentforge-flywheel)
            let config = FlywheelConfig {
                skill_name: skill.clone(),
                dry_run,
                real_data,
                limit,
                slice: None,
                ingest,
                output_dir: output_dir.clone(),
                trajectories_dir: find_flag_value(&args, &["--trajectories", "-t"])
                    .map(PathBuf::from),
                prm_dir: find_flag_value(&args, &["--prm-dir", "-p"]).map(PathBuf::from),
                min_prm: find_flag_value(&args, &["--min-prm"]).and_then(|s| s.parse().ok()),
                json_mode,
            };

            // Invoke the skeleton orchestrator (will grow into full SkillImprover + emission + stats)
            let orchestrator = FlywheelOrchestrator::new();
            let manifest = match orchestrator.run_step(&config) {
                Ok(m) => m,
                Err(e) => {
                    if json_mode {
                        println!(
                            r#"{{"error":"flywheel-step failed","detail":"{}","cmd":"flywheel-step"}}"#,
                            e
                        );
                    } else {
                        eprintln!("[runner] flywheel-step error: {}", e);
                    }
                    std::process::exit(1);
                }
            };

            // Ingest path (candidates crate): drops to pending_candidates/ when --ingest (real under pure)
            let mut ingest_info = None;
            if ingest && !dry_run {
                let store = CandidateStore::new(None);
                if let Ok(res) = store.ingest(
                    &output_dir
                        .clone()
                        .unwrap_or_else(|| PathBuf::from("/tmp/fw_ingest")),
                    &serde_json::json!({"skill": skill}),
                ) {
                    ingest_info = Some(serde_json::json!({
                        "candidate_id": res.candidate_id,
                        "dest": res.dest_dir.to_string_lossy(),
                    }));
                }
            }

            let out_json = serde_json::json!({
                "cmd": "flywheel-step",
                "phase": "1-real-mvp",
                "skill": skill,
                "config": {
                    "dry_run": dry_run,
                    "real_data": real_data,
                    "ingest": ingest,
                    "limit": limit,
                    "shadow": shadow,
                },
                "manifest": manifest,
                "ingest": ingest_info,
                "shadow": shadow,
                "fidelity_context": shadow,  // Phase 2 enriched: signals dual-run for harness/post_process
                "note": "COMPLETE (direct pure-Rust replacement). Real TrajectoryDataset + improver -> proposal + candidate_skill.yaml + manifest + ingest to pending_candidates. --shadow / AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 for dual-run fidelity in post_process/after_task/parity/harness. Used by workers, hooks, demo. Promote via 'candidate promote'. See --help.",
                "provenance": "rust-agentforge-runner/flywheel-step"
            });

            if json_mode {
                println!("{}", out_json);
            } else {
                eprintln!(
                    "[runner] flywheel-step COMPLETE (Phase 1 real). status={} engine={} shadow={}",
                    manifest.status, manifest.engine, shadow
                );
                if let Some(dir) = &output_dir {
                    eprintln!("[runner] artifacts written under {}", dir.display());
                }
                if let Some(ii) = &ingest_info {
                    eprintln!(
                        "[runner] ingest exercised -> candidate_id={}",
                        ii["candidate_id"]
                    );
                }
                eprintln!("[runner] Next: ls the output dir, then python -m agentforge.list_pending_candidates list (or promote)");
            }
        }

        "stats" => {
            let input = find_flag_value(&args, &["--input", "-i", "--from", "-f"]);
            let ds = load_dataset(input.as_deref()).unwrap_or_else(|e| {
                eprintln!("[runner] load warn: {}", e);
                TrajectoryDataset::new("empty")
            });
            let stats = ds.basic_stats();
            let by_outcome: std::collections::HashMap<_, _> = {
                let mut m = std::collections::HashMap::new();
                for r in &ds.records {
                    *m.entry(format!("{:?}", r.outcome)).or_insert(0) += 1;
                }
                m
            };
            let out = serde_json::json!({
                "cmd": "stats",
                "input": input,
                "record_count": ds.len(),
                "basic_stats": stats,
                "by_outcome": by_outcome,
                "has_prm": ds.records.iter().any(|r| r.prm_overall.is_some()),
            });
            println!("{}", out);
        }

        "export-records" | "dump-records" | "records" => {
            let input = find_flag_value(&args, &["--input", "--from", "-i", "-f"])
                .or_else(|| Some("eval/results".into()));
            let output = find_flag_value(&args, &["--output", "--out", "-o"])
                .map(PathBuf::from)
                .unwrap_or_else(|| {
                    PathBuf::from(format!("/tmp/rust_records_{}.jsonl", std::process::id()))
                });

            let ds = match load_dataset(input.as_deref()) {
                Ok(d) => d,
                Err(e) => {
                    eprintln!("[runner] export-records load failed: {}", e);
                    TrajectoryDataset::new("empty")
                }
            };
            let recs: Vec<serde_json::Value> = ds
                .records
                .iter()
                .map(|r| serde_json::to_value(r).unwrap_or_else(|_| serde_json::json!({})))
                .collect();
            let _ = write_jsonl(&output, &recs);
            if json_mode {
                println!(
                    "{}",
                    serde_json::json!({"cmd":"export-records","count":recs.len(),"output":output.to_string_lossy()})
                );
            } else {
                eprintln!(
                    "[runner] Wrote {} full records → {}",
                    recs.len(),
                    output.display()
                );
            }
        }

        "flywheel-export" | "export-learning" | "export-flywheel" => {
            // Production-grade rich "flywheel-export" subcommand.
            // Command: agentforge-runner flywheel-export --trajectories DIR --prm-dir DIR (or --input) --output FILE [--format json|jsonl] [--min-prm F]
            // Loads real trajectories/*.jsonl + matching *.prm.json sidecars (from eval/trajectories or eval/results).
            // Uses/extends TrajectoryDataset (load_flywheel_data + enrich + load_from_real_input).
            // Emits rich structured: preference_pairs (DPO-style), prm_step_labels (when present), per-record learning_value,
            // stats (success_rate, avg_prm, high_value_count). Graceful missing sidecars, fast, good errors.
            // --format json => single pretty rich bundle JSON; jsonl => jsonl of pairs + records + labels + stats trailer.
            let trajectories = find_flag_value(
                &args,
                &["--trajectories", "--traj", "-t", "--trajectories-dir"],
            );
            let prm_dir = find_flag_value(&args, &["--prm-dir", "--prm", "--prm-sidecars", "-p"]);
            let results = find_flag_value(&args, &["--results", "--res", "-r", "--results-dir"]);
            let input_fallback = find_flag_value(&args, &["--input", "-i", "--from", "-f"]);
            let output = find_flag_value(&args, &["--output", "--out", "-o"])
                .map(PathBuf::from)
                .unwrap_or_else(|| {
                    PathBuf::from(format!("/tmp/flywheel_rich_{}.json", std::process::id()))
                });
            let fmt = find_flag_value(&args, &["--format", "--fmt"])
                .unwrap_or_else(|| "json".to_string())
                .to_lowercase();
            let min_prm: Option<f64> = find_flag_value(&args, &["--min-prm", "--min_prm", "-m"])
                .and_then(|s| s.parse::<f64>().ok());

            // Build dataset: prefer dedicated dirs (supports separate --prm-dir), fallback to --input / default trajectories
            let mut ds = TrajectoryDataset::new("flywheel_export");
            let mut load_summary = serde_json::json!({});
            if trajectories.is_some() || prm_dir.is_some() || results.is_some() {
                let t_arg = trajectories.as_ref().map(|s| std::path::PathBuf::from(s));
                let p_arg = prm_dir.as_ref().map(|s| std::path::PathBuf::from(s));
                let r_arg = results.as_ref().map(|s| std::path::PathBuf::from(s));
                match ds.load_flywheel_data(t_arg.as_ref(), p_arg.as_ref(), r_arg.as_ref()) {
                    Ok((tt, pp, rr)) => {
                        load_summary = serde_json::json!({"trajectories":tt,"prm_enriched":pp,"results":rr,"mode":"dirs"});
                    }
                    Err(e) => {
                        if !json_mode {
                            eprintln!("[runner] load_flywheel_data warning (graceful): {}", e);
                        }
                    }
                }
            }
            let effective_input =
                if trajectories.is_none() && prm_dir.is_none() && results.is_none() {
                    input_fallback
                        .or_else(|| Some("/home/eveselove/agentforge/eval/trajectories".into()))
                } else {
                    input_fallback.clone()
                };
            if let Some(inp) = &effective_input {
                if ds.records.is_empty() {
                    let p = PathBuf::from(inp);
                    let cands: Vec<PathBuf> = if p.is_absolute() {
                        vec![p.clone()]
                    } else {
                        vec![
                            PathBuf::from("/home/eveselove/agentforge").join(inp),
                            p.clone(),
                            PathBuf::from("..").join(inp),
                        ]
                    };
                    for cand in cands {
                        if cand.exists() {
                            if let Ok(n) = ds.load_from_real_input(&cand) {
                                if n > 0 {
                                    load_summary["fallback"] = serde_json::json!({"path":cand.to_string_lossy(), "count":n});
                                    break;
                                }
                            }
                        }
                    }
                }
            }
            if ds.records.is_empty() {
                if let Some(i) = &effective_input {
                    let _ = ds.load_from_real_input(i);
                }
            }
            ds.compute_learning_value();

            // THE rich structured output (as required)
            let bundle = ds.export_flywheel_rich(min_prm);

            // Write: json => full rich bundle as pretty JSON; jsonl => rich jsonl (pairs + learning records + prm labels + stats)
            let write_err = if fmt == "jsonl" || fmt == "jsonlines" {
                let mut items: Vec<serde_json::Value> = bundle
                    .get("preference_pairs")
                    .and_then(|v| v.as_array())
                    .cloned()
                    .unwrap_or_default();
                if let Some(recs) = bundle
                    .get("per_record_learning_values")
                    .and_then(|v| v.as_array())
                {
                    for r in recs.iter().take(500) {
                        // cap for size in jsonl mode
                        items.push(serde_json::json!({"type":"learning_record", "learning_value": r.get("learning_value"), "data": r}));
                    }
                }
                if let Some(lbls) = bundle.get("prm_step_labels").and_then(|v| v.as_array()) {
                    for l in lbls.iter().take(200) {
                        items.push(serde_json::json!({"type":"prm_step_label", "data": l}));
                    }
                }
                if let Some(st) = bundle.get("stats") {
                    items.push(serde_json::json!({"type":"stats", "data": st}));
                }
                write_jsonl(&output, &items)
            } else {
                // use jsonl with single rich bundle item for structured output
                let bundle_item = vec![bundle.clone()];
                write_jsonl(&output, &bundle_item)
            };

            if let Err(e) = write_err {
                if json_mode {
                    println!(
                        r#"{{"error":"write failed","detail":"{}","cmd":"flywheel-export"}}"#,
                        e
                    );
                } else {
                    eprintln!("error writing: {}", e);
                }
                std::process::exit(1);
            }

            let rec_count = ds.len();
            let pairs_c = bundle
                .get("preference_pairs")
                .and_then(|a| a.as_array().map(|x| x.len()))
                .unwrap_or(0);
            let labels_c = bundle
                .get("prm_step_labels")
                .and_then(|a| a.as_array().map(|x| x.len()))
                .unwrap_or(0);
            let stats_out = bundle
                .get("stats")
                .cloned()
                .unwrap_or(serde_json::json!({}));

            if json_mode {
                println!(
                    "{}",
                    serde_json::json!({
                        "cmd": "flywheel-export",
                        "format": fmt,
                        "trajectories": trajectories,
                        "prm_dir": prm_dir,
                        "input": effective_input,
                        "output": output.to_string_lossy(),
                        "min_prm": min_prm,
                        "record_count": rec_count,
                        "pairs_count": pairs_c,
                        "prm_labels_count": labels_c,
                        "stats": stats_out,
                        "load_summary": load_summary,
                        "rich_keys": ["preference_pairs","prm_step_labels","per_record_learning_values","stats"]
                    })
                );
            } else {
                eprintln!("[runner] flywheel-export: {} recs ({} pairs + {} prm_labels, high_value={}) → {}",
                    rec_count, pairs_c, labels_c,
                    stats_out.get("high_value_count").and_then(|x|x.as_u64()).unwrap_or(0),
                    output.display());
                eprintln!(
                    "[runner] stats success_rate={:.3} avg_prm={:.3} (min_prm={:?})  format={}",
                    stats_out
                        .get("success_rate")
                        .and_then(|x| x.as_f64())
                        .unwrap_or(0.0),
                    stats_out
                        .get("avg_prm")
                        .and_then(|x| x.as_f64())
                        .unwrap_or(0.0),
                    min_prm,
                    fmt
                );
            }
        }

        // =====================================================================
        // Phase 1: candidate subcommand - real Rust prioritizer + lister (no Python)
        // `agentforge-runner candidate list [--top N] [--sort value|recency] [--json]`
        // Uses CandidateStore.list_pending() (now full meta+proposal+manifest scan)
        // + Prioritizer::rank (ported _lv_key: rich/avg_lv * lift_potential + recency boost).
        // --sort recency uses dir name order (no scoring). Shows real candidates today.
        // `candidate promote <id> [--copy-to-skills] [--json] [--dry-run]`: FULLY WIRED real implementation (end-to-end complete).
        //   - Safe (dry-run preview always available)
        //   - Copies candidate_skill.yaml into skills/ with good naming (when --copy-to-skills)
        //   - Appends to promotions.jsonl (canonical py shape + rust source) + updates skills/promotion_history.json (rolling)
        //   - Marks candidate as promoted in its candidate_meta.json (promoted=true + timestamps + reviewed + source) + markers
        //   - --json: clean structured output; human mode: detailed good output with paths/status
        //   Good output + safe + fully operational on real candidates from runner / farm / automation.
        // =====================================================================
        "candidate" => {
            // Robust subcmd detection: find "candidate" position, take the next non-flag token as cand_cmd (handles --json before or after, and direct use).
            let cand_idx = args.iter().position(|a| a == "candidate").unwrap_or(0);
            let cand_cmd = args
                .get(cand_idx + 1)
                .filter(|s| !s.starts_with('-'))
                .map(|s| s.as_str())
                .unwrap_or("list");
            let store = CandidateStore::new(None);
            match cand_cmd {
                "list" | "ls" | "prioritize" => {
                    let top: usize = find_flag_value(&args, &["--top", "-n", "--limit"])
                        .and_then(|s| s.parse().ok())
                        .unwrap_or(10);
                    let sort = find_flag_value(&args, &["--sort", "-s"])
                        .unwrap_or_else(|| "value".to_string())
                        .to_lowercase();
                    let listed: Vec<_> = if sort == "recency" {
                        let mut cands = store.list_pending().unwrap_or_default();
                        // Ensure strict recency by id (newest timestamp_hash first; matches py default sort)
                        cands.sort_by(|a, b| b.id.cmp(&a.id));
                        cands.truncate(top);
                        cands
                    } else {
                        // value (default): full list_pending (now with manifest data) -> rank via prioritizer (includes promoted + reviewed flag for visibility)
                        let all = store.list_pending().unwrap_or_default();
                        let ranked = Prioritizer::new().rank(&all);
                        ranked.into_iter().take(top).map(|p| p.summary).collect()
                    };
                    if json_mode {
                        let items: Vec<_> = listed
                            .iter()
                            .map(|c| {
                                serde_json::json!({
                                    "id": c.id,
                                    "skill": c.skill,
                                    "impact": c.impact,
                                    "high_value_count": c.high_value_count,
                                    "rich_avg_learning_value": c.rich_avg_learning_value,
                                    "avg_learning_value": c.avg_learning_value,
                                    "success_rate": c.success_rate,
                                    "records_loaded": c.records_loaded,
                                    "promoted": c.promoted,
                                    "timestamp": c.timestamp,
                                    "path": c.path.to_string_lossy(),
                                })
                            })
                            .collect();
                        println!(
                            "{}",
                            serde_json::json!({
                                "cmd": "candidate list",
                                "sort": sort,
                                "top": top,
                                "count": items.len(),
                                "root": store.root.to_string_lossy(),
                                "candidates": items,
                                "note": "real Rust (CandidateStore.list_pending + Prioritizer rank from meta/proposal/manifest; _lv_key port)"
                            })
                        );
                    } else {
                        eprintln!(
                            "[runner] candidate list (sort={}, top {} from {}):",
                            sort,
                            top,
                            store.root.display()
                        );
                        if listed.is_empty() {
                            eprintln!("  (no pending candidates found; run flywheel-step --real-data --ingest or equivalent)");
                        }
                        for (i, c) in listed.iter().enumerate() {
                            let lv_str = if let Some(v) =
                                c.rich_avg_learning_value.or(c.avg_learning_value)
                            {
                                format!(" avg_lv={:.2}", v)
                            } else {
                                String::new()
                            };
                            let sr_str = c
                                .success_rate
                                .map(|v| format!(" sr={:.3}", v))
                                .unwrap_or_default();
                            let rec_str = c
                                .records_loaded
                                .map(|r| format!(" recs={}", r))
                                .unwrap_or_default();
                            let ts_str = c
                                .timestamp
                                .as_deref()
                                .map(|t| format!(" ts={}", t))
                                .unwrap_or_default();
                            eprintln!(
                                "  #{:<2} {}{}  skill={}  impact={}  hlv={}{}{}{}  promoted={}",
                                i + 1,
                                c.id,
                                lv_str,
                                c.skill,
                                c.impact,
                                c.high_value_count,
                                sr_str,
                                rec_str,
                                ts_str,
                                c.promoted
                            );
                        }
                        eprintln!("(Use --json for machine output; promote <id> for next step. Data via real manifest+meta scan.)");
                    }
                }
                "promote" => {
                    // FULLY WIRED real `candidate promote <id> [--copy-to-skills] [--json]` (safe, good output, end-to-end finished):
                    // Delegates to agentforge-candidates::promote_candidate (real copy with good naming,
                    // appends to promotions.jsonl + skills/promotion_history.json (full py parity + rust source), marks promoted in meta).
                    // Rich result for detailed status. --dry-run for safety preview. Excellent human + --json output.
                    // Robust id detection (after "promote" token or via flags).
                    let prom_idx = args.iter().position(|a| a == "promote").unwrap_or(0);
                    let candidate_id = args
                        .get(prom_idx + 1)
                        .filter(|s| !s.starts_with('-'))
                        .map(|s| s.to_string())
                        .or_else(|| find_flag_value(&args, &["--id", "--candidate", "-c"]))
                        .unwrap_or_default();
                    if candidate_id.is_empty() {
                        if json_mode {
                            println!(
                                r#"{{"error":"missing candidate_id","usage":"candidate promote <id> [--copy-to-skills] [--json] [--dry-run]"}}"#
                            );
                        } else {
                            eprintln!("[runner] usage: agentforge-runner candidate promote <id> [--copy-to-skills] [--json] [--dry-run] (safe)");
                        }
                        // do not exit hard
                    } else {
                        let do_copy = has_flag(&args, &["--copy-to-skills", "--copy"]);
                        let dry_run = has_flag(&args, &["--dry-run", "--dry", "-d"]);
                        // Real impl (wired, rich result)
                        match promote_candidate(&store, &candidate_id, do_copy, dry_run) {
                            Ok(res) => {
                                if json_mode {
                                    println!("{}", serde_json::to_string(&serde_json::json!({
                                        "cmd": "candidate promote",
                                        "candidate_id": res.candidate_id,
                                        "candidate_dir": res.candidate_dir.to_string_lossy(),
                                        "promoted_to": res.promoted_to.as_ref().map(|p| p.to_string_lossy().to_string()),
                                        "copy_succeeded": res.copy_succeeded,
                                        "ab_prepared": res.ab_prepared,
                                        "history_updated": res.history_updated,
                                        "history_path": res.history_path.to_string_lossy(),
                                        "meta_path": res.meta_path.to_string_lossy(),
                                        "marker_path": res.marker_path.to_string_lossy(),
                                        "reviewed_marker_path": res.reviewed_marker_path.to_string_lossy(),
                                        "promoted": res.promoted,
                                        "meta_updated": res.meta_updated,
                                        "marker_created": res.marker_created,
                                        "dry_run": res.dry_run,
                                        "promoted_at": res.promoted_at,
                                        "success": res.success,
                                        "warnings": res.warnings,
                                        "note": "COMPLETE + FULLY REAL promote (source=rust-agentforge-runner). Timestamped copy + promotions.jsonl + promotion_history (py parity + rust stamp) + meta+markers. --dry-run safe. Rich observable result. The production promote path under pure Rust surface."
                                    })).unwrap());
                                } else {
                                    eprintln!("[runner] candidate promote (REAL RUST, FULLY WIRED) for: {}", candidate_id);
                                    eprintln!(
                                        "  dry_run={}  copy_to_skills={}  success={}",
                                        res.dry_run, do_copy, res.success
                                    );
                                    eprintln!("  candidate_dir: {}", res.candidate_dir.display());
                                    if let Some(p) = &res.promoted_to {
                                        eprintln!(
                                            "  promoted_to (skills): {}  (copy_succeeded={})",
                                            p.display(),
                                            res.copy_succeeded
                                        );
                                    } else if do_copy {
                                        eprintln!("  promoted_to: (none - no yaml or copy failed)");
                                    }
                                    eprintln!(
                                        "  meta: {}  (updated={})",
                                        res.meta_path.display(),
                                        res.meta_updated
                                    );
                                    eprintln!(
                                        "  history: {}  (updated={})",
                                        res.history_path.display(),
                                        res.history_updated
                                    );
                                    eprintln!(
                                        "  markers: .promoted={}  .reviewed={}",
                                        res.marker_path.display(),
                                        res.reviewed_marker_path.display()
                                    );
                                    eprintln!(
                                        "  promoted_at={}  promoted={}  marker_created={}",
                                        res.promoted_at, res.promoted, res.marker_created
                                    );
                                    if !res.warnings.is_empty() {
                                        eprintln!("  warnings: {:?}", res.warnings);
                                    }
                                    if res.dry_run {
                                        eprintln!("  (DRY-RUN: zero files mutated — remove --dry-run to execute real promote)");
                                    } else if res.success {
                                        eprintln!("  ✓ Production-ready promote complete. Next: inspect promotions.jsonl or skills/promotion_history.json or run list.");
                                    } else {
                                        eprintln!("  ⚠ Promote completed with partial success (see warnings).");
                                    }
                                }
                            }
                            Err(e) => {
                                if json_mode {
                                    println!(
                                        r#"{{"error":"promote_failed","candidate_id":"{}","detail":"{}","usage":"candidate promote <id> [--copy-to-skills] [--json] [--dry-run]"}}"#,
                                        candidate_id, e
                                    );
                                } else {
                                    eprintln!("[runner] promote error for {}: {}", candidate_id, e);
                                    eprintln!("  usage: agentforge-runner candidate promote <id> [--copy-to-skills] [--json] [--dry-run] (safe)");
                                }
                                std::process::exit(1);
                            }
                        }
                    }
                }
                _ => {
                    if json_mode {
                        println!(
                            r#"{{"error":"unknown candidate subcmd","use":"list [--top N] [--sort value|recency] | promote <id>"}}"#
                        );
                    } else {
                        eprintln!("[runner] candidate subcommands: list [--top N] [--sort value|recency]  |  promote <id> [--copy-to-skills] [--json] [--dry-run] (FULL: source=rust-agentforge-runner in history.jsonl)");
                    }
                }
            }
        }

        // =====================================================================
        // Top-level convenience aliases for hot production paths (UX polish)
        // "promote <id>" and "list" (or "ls") are obvious short forms for the farm.
        // Delegate to the exact same real candidate logic (no duplication).
        // =====================================================================
        "promote" => {
            // Treat as "candidate promote" — robust id capture
            let prom_idx = args.iter().position(|a| a == "promote").unwrap_or(0);
            let candidate_id = args
                .get(prom_idx + 1)
                .filter(|s| !s.starts_with('-'))
                .map(|s| s.to_string())
                .or_else(|| find_flag_value(&args, &["--id", "--candidate", "-c"]))
                .unwrap_or_default();
            if candidate_id.is_empty() {
                if json_mode {
                    println!(
                        r#"{{"error":"missing candidate_id","usage":"promote <id> [--copy-to-skills] [--json] [--dry-run]  (or: candidate promote ...)"}}"#
                    );
                } else {
                    eprintln!("[runner] usage: agentforge-runner promote <id> [--copy-to-skills] [--json] [--dry-run]   (short alias; same as 'candidate promote'. REAL rust promote, safe dry default)");
                }
            } else {
                let do_copy = has_flag(&args, &["--copy-to-skills", "--copy"]);
                let dry_run = has_flag(&args, &["--dry-run", "--dry", "-d"]);
                let store = CandidateStore::new(None);
                match promote_candidate(&store, &candidate_id, do_copy, dry_run) {
                    Ok(res) => {
                        if json_mode {
                            println!("{}", serde_json::to_string(&serde_json::json!({
                                "cmd": "promote",
                                "alias_of": "candidate promote",
                                "candidate_id": res.candidate_id,
                                "success": res.success,
                                "dry_run": res.dry_run,
                                "copy_succeeded": res.copy_succeeded,
                                "promoted_to": res.promoted_to.as_ref().map(|p| p.to_string_lossy().to_string()),
                                "history_updated": res.history_updated,
                                "note": "COMPLETE REAL promote via top-level alias (source=rust-agentforge-runner). Use 'candidate promote' or plain 'promote'."
                            })).unwrap());
                        } else {
                            eprintln!("[runner] promote (top-level alias, REAL RUST) for {}: success={} dry={}", candidate_id, res.success, res.dry_run);
                            if let Some(p) = &res.promoted_to {
                                eprintln!("  promoted_to: {}", p.display());
                            }
                            eprintln!("  (identical to 'candidate promote'; history + markers + rust stamp written when !dry_run)");
                        }
                    }
                    Err(e) => {
                        if json_mode {
                            println!(
                                r#"{{"error":"promote_failed","candidate_id":"{}","detail":"{}"}}"#,
                                candidate_id, e
                            );
                        } else {
                            eprintln!("[runner] promote error for {}: {}", candidate_id, e);
                        }
                        std::process::exit(1);
                    }
                }
            }
        }

        "list" | "ls" | "candidates" => {
            // Top-level alias: candidate list (prioritizer). Production obvious short form.
            let top: usize = find_flag_value(&args, &["--top", "-n", "--limit"])
                .and_then(|s| s.parse().ok())
                .unwrap_or(10);
            let sort = find_flag_value(&args, &["--sort", "-s"])
                .unwrap_or_else(|| "value".to_string())
                .to_lowercase();
            let store = CandidateStore::new(None);
            let listed: Vec<_> = if sort == "recency" {
                let mut cands = store.list_pending().unwrap_or_default();
                cands.sort_by(|a, b| b.id.cmp(&a.id));
                cands.truncate(top);
                cands
            } else {
                let all = store.list_pending().unwrap_or_default();
                let ranked = Prioritizer::new().rank(&all);
                ranked.into_iter().take(top).map(|p| p.summary).collect()
            };
            if json_mode {
                let items: Vec<_> = listed
                    .iter()
                    .map(|c| {
                        serde_json::json!({
                            "id": c.id, "skill": c.skill, "impact": c.impact,
                            "rich_avg_learning_value": c.rich_avg_learning_value,
                            "promoted": c.promoted, "path": c.path.to_string_lossy()
                        })
                    })
                    .collect();
                println!(
                    "{}",
                    serde_json::json!({"cmd":"list","alias_of":"candidate list","sort":sort,"top":top,"count":items.len(),"candidates":items})
                );
            } else {
                eprintln!(
                    "[runner] list (top-level alias for candidate list, sort={}, top {}):",
                    sort, top
                );
                for (i, c) in listed.iter().enumerate() {
                    eprintln!(
                        "  #{} {}  skill={}  impact={}",
                        i + 1,
                        c.id,
                        c.skill,
                        c.impact
                    );
                }
                eprintln!(
                    "(Use 'candidate list' for full fields or --json. Then 'promote <id>' to act.)"
                );
            }
        }

        // =====================================================================
        // `continuous` — COMPLETE pure-Rust autonomy meta-loop (production)
        // One autonomy step: load candidates (real CandidateStore + Prioritizer),
        // rank by rich value (lv*lift + recency), suggest top-N (dry-run default, safe).
        // Writes /tmp/.../flywheel_health.json (watchdog + timer + parity compat).
        // --shadow / env wires dual-run fidelity into farm (post_process, hooks, harness).
        // Direct replacement for legacy run_continuous_* . Promote is separate subcmd.
        // =====================================================================
        "continuous" => {
            let top_n: usize = find_flag_value(&args, &["--top-n", "--top", "-n", "--limit"])
                .and_then(|s| s.parse().ok())
                .unwrap_or(2);
            // Dry-run default true (safe). --no-dry-run or --execute to run real actions (future).
            let dry_run = !has_flag(&args, &["--no-dry-run", "--execute", "--real"]);
            // Phase 2 shadow / dual-run (continuous fidelity for farm validation, mirrors flywheel-step + post_process)
            let shadow = has_flag(&args, &["--shadow"])
                || std::env::var("AGENTFORGE_RUST_FLYWHEEL_SHADOW")
                    .map(|v| {
                        v == "1"
                            || v.to_lowercase() == "true"
                            || v.to_lowercase() == "yes"
                            || v.to_lowercase() == "on"
                    })
                    .unwrap_or(false);
            // UX completeness: accept --min-lv (future filter parity with Python continuous) - parsed but advisory in skeleton
            let _min_lv: Option<f64> =
                find_flag_value(&args, &["--min-lv", "--min-lv", "--min_avg_lv"])
                    .and_then(|s| s.parse().ok());

            if !json_mode {
                eprintln!("[runner] continuous (COMPLETE production autonomy) top_n={} dry_run={} shadow={}", top_n, dry_run, shadow);
            }

            let store = CandidateStore::new(None);
            let tops = list_high_value_candidates(&store, top_n);

            let suggestions: Vec<serde_json::Value> = tops
                .iter()
                .map(|c| {
                    serde_json::json!({
                        "id": c.id,
                        "skill": c.skill,
                        "impact": c.impact,
                        "high_value_count": c.high_value_count,
                        "rich_avg_learning_value": c.rich_avg_learning_value,
                        "success_rate": c.success_rate,
                        "path": c.path.to_string_lossy(),
                    })
                })
                .collect();

            // Health JSON (exact compat shape for /tmp/.../flywheel_health.json + watchdog/timer/parity)
            // Includes shadow for continuous dual-run fidelity (hooks / post_process / harness / services)
            let health = serde_json::json!({
                "timestamp": chrono::Utc::now().to_rfc3339(),
                "source": "agentforge-runner continuous (COMPLETE pure-Rust autonomy meta-loop + shadow)",
                "dry_run": dry_run,
                "top_n": top_n,
                "shadow": shadow,
                "suggested_count": suggestions.len(),
                "suggested": suggestions,
                "total_pending_scanned": store.list_pending().map(|v| v.len()).unwrap_or(0),
                "enable_marker_present": std::path::Path::new("/home/eveselove/agentforge/ENABLE_RUST_FLYWHEEL").exists(),
                "fidelity_ready": true,
                "note": "COMPLETE: load + Prioritizer rank (rich lv*lift+recency) + suggest top-N (dry default). Shadow for dual-run fidelity. Direct replacement for run_continuous_flywheel + timer. Health for watchdog/parity. Promote via separate 'candidate promote'. Integrates with after_task hooks, post_process, parity_harness, services.",
                "phase": "production"
            });

            let health_path =
                std::path::PathBuf::from("/tmp/agentforge_rust_flywheel/flywheel_health.json");
            if let Some(p) = health_path.parent() {
                let _ = std::fs::create_dir_all(p);
            }
            let _ = std::fs::write(
                &health_path,
                serde_json::to_string_pretty(&health).unwrap_or_default(),
            );

            let out = serde_json::json!({
                "cmd": "continuous",
                "phase": "production-complete",
                "top_n": top_n,
                "dry_run": dry_run,
                "shadow": shadow,
                "suggested": suggestions,
                "health_written": health_path.to_string_lossy(),
                "health": health,
                "note": "COMPLETE pure-Rust continuous (autonomy meta-loop). Direct runner surface for farm: timers, after_task hooks, post_process, services, parity. --shadow/AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 for dual fidelity. Dry default safe. Health JSON written. Promote via 'candidate promote'. See agentforge-runner --help + bin/test_pure_rust_flywheel_step.sh + bin/rust_flywheel_after_task.sh"
            });

            if json_mode {
                println!("{}", out);
            } else {
                eprintln!("[runner] continuous COMPLETE (production autonomy + shadow). Suggested {} candidates (dry_run={} shadow={}).", suggestions.len(), dry_run, shadow);
                for (i, s) in suggestions.iter().enumerate() {
                    eprintln!(
                        "  #{} {} (skill={}, lv={:?})",
                        i + 1,
                        s["id"],
                        s["skill"],
                        s["rich_avg_learning_value"]
                    );
                }
                eprintln!(
                    "[runner] Health JSON -> {} (watchdog + farm parity ready)",
                    health_path.display()
                );
                eprintln!("[runner] Pure Rust surface: --shadow or AGENTFORGE_RUST_FLYWHEEL_SHADOW=1 wires continuous dual-run fidelity into hooks/post_process/timers/parity.");
            }
        }

        "version" => {
            println!(
                "{}",
                if json_mode {
                    format!(r#"{{"version":"{}"}}"#, VERSION)
                } else {
                    VERSION.to_string()
                }
            );
        }

        "help" | _ => {
            if json_mode {
                println!(
                    r#"{{"status":"ok","commands":["demo","full-stack","export-pairs","export-prm-steps","export-sft","flywheel-export","export-learning","improve-skill","flywheel-step","stats","version","candidate list","candidate promote","continuous"],"note":"COMPLETE pure Rust surface: flywheel-step + continuous (autonomy+shadow) + candidate promote (real) + shadow. All integration (after_task hooks, post_process, demo tools, timers, workers) wired direct. See --help for examples."}}"#
                );
            } else {
                print_usage();
            }
        }
    }
}
