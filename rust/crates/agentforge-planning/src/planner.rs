use serde::{Deserialize, Serialize};
use std::collections::HashSet;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum SubtaskStatus {
    Pending,
    Running,
    Done,
    Failed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Subtask {
    pub id: String,
    pub description: String,
    pub dependencies: Vec<String>,
    pub status: SubtaskStatus,
    pub result: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Plan {
    pub goal: String,
    pub subtasks: Vec<Subtask>,
}

pub struct HierarchicalPlanner;

impl HierarchicalPlanner {
    pub fn new() -> Self {
        Self
    }

    /// Very basic decomposition (will be replaced by LLM-based in future).
    pub fn decompose(&self, goal: &str) -> Plan {
        let subtasks = vec![
            Subtask {
                id: "1".to_string(),
                description: format!("Understand and break down: {}", goal),
                dependencies: vec![],
                status: SubtaskStatus::Pending,
                result: None,
            },
            Subtask {
                id: "2".to_string(),
                description: "Design the solution and identify risks".to_string(),
                dependencies: vec!["1".to_string()],
                status: SubtaskStatus::Pending,
                result: None,
            },
            Subtask {
                id: "3".to_string(),
                description: "Implement the core changes".to_string(),
                dependencies: vec!["2".to_string()],
                status: SubtaskStatus::Pending,
                result: None,
            },
            Subtask {
                id: "4".to_string(),
                description: "Test, verify and document".to_string(),
                dependencies: vec!["3".to_string()],
                status: SubtaskStatus::Pending,
                result: None,
            },
        ];

        Plan {
            goal: goal.to_string(),
            subtasks,
        }
    }

    /// Returns subtasks in an order that respects dependencies (simple topological sort).
    pub fn get_execution_order(&self, plan: &Plan) -> Vec<Subtask> {
        let mut result = Vec::new();
        let mut completed: HashSet<String> = HashSet::new();

        loop {
            let mut added = false;

            for sub in &plan.subtasks {
                if completed.contains(&sub.id) {
                    continue;
                }

                let deps_ready = sub.dependencies.iter().all(|d| completed.contains(d));

                if deps_ready {
                    result.push(sub.clone());
                    completed.insert(sub.id.clone());
                    added = true;
                }
            }

            if !added {
                break;
            }
        }

        result
    }

    /// Execute the plan sequentially with dependency respect.
    pub fn execute_plan<F>(&self, mut plan: Plan, mut executor: F) -> Plan
    where
        F: FnMut(&mut Subtask) -> Result<String, String>,
    {
        let order = self.get_execution_order(&plan);

        for sub in order {
            // Find mutable reference
            if let Some(subtask) = plan.subtasks.iter_mut().find(|s| s.id == sub.id) {
                println!("[Planner] Running: {}", subtask.description);

                match executor(subtask) {
                    Ok(res) => {
                        subtask.result = Some(res);
                        subtask.status = SubtaskStatus::Done;
                    }
                    Err(e) => {
                        subtask.result = Some(e);
                        subtask.status = SubtaskStatus::Failed;
                        break;
                    }
                }
            }
        }

        plan
    }
}

/// Checkpoint / resume support (matches Python PlanCheckpoint).
impl Plan {
    pub fn to_json(&self) -> Result<String, String> {
        serde_json::to_string_pretty(self).map_err(|e| e.to_string())
    }

    pub fn from_json(s: &str) -> Result<Self, String> {
        serde_json::from_str(s).map_err(|e| e.to_string())
    }

    pub fn save_checkpoint(&self, path: &std::path::Path) -> Result<(), String> {
        let json = self.to_json()?;
        std::fs::write(path, json).map_err(|e| e.to_string())
    }

    pub fn load_checkpoint(path: &std::path::Path) -> Result<Self, String> {
        let s = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
        Self::from_json(&s)
    }
}

/// Simple dependency graph + wave scheduler (Kahn-style, for future parallel exec).
pub struct DependencyGraph;

impl DependencyGraph {
    pub fn topo_sort(_subtasks: &[Subtask]) -> Vec<String> {
        // Reuse planner logic for now; extendable to parallel waves.
        vec![] // placeholder, real impl would compute levels
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn planner_decompose_and_order() {
        let p = HierarchicalPlanner::new();
        let plan = p.decompose("test goal");
        assert_eq!(plan.subtasks.len(), 4);
        let order = p.get_execution_order(&plan);
        assert!(!order.is_empty());
        // 1 has no deps, should be first
        assert_eq!(order[0].id, "1");
    }

    #[test]
    fn plan_checkpoint_roundtrip() {
        let p = HierarchicalPlanner::new();
        let plan = p.decompose("checkpoint test");
        let json = plan.to_json().unwrap();
        let restored = Plan::from_json(&json).unwrap();
        assert_eq!(restored.goal, plan.goal);
    }
}
