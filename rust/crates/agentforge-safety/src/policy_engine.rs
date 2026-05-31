use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum Decision {
    Allow,
    Block,
    RequireApproval,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ActionDecision {
    pub decision: Decision,
    pub reason: String,
    pub policy_name: Option<String>,
    pub risk_score: f64, // 0.0 safe .. 1.0 extremely dangerous (mirrors Python)
    pub metadata: HashMap<String, serde_json::Value>,
}

pub type PolicyRule = fn(&str, &HashMap<String, String>) -> Option<ActionDecision>;

pub struct PolicyEngine {
    rules: Vec<PolicyRule>,
}

impl PolicyEngine {
    pub fn new() -> Self {
        Self { rules: Vec::new() }
    }

    pub fn add_rule(&mut self, rule: PolicyRule) {
        self.rules.push(rule);
    }

    pub fn evaluate(&self, action_type: &str, context: &HashMap<String, String>) -> ActionDecision {
        for rule in &self.rules {
            if let Some(decision) = rule(action_type, context) {
                return decision;
            }
        }

        ActionDecision {
            decision: Decision::Allow,
            reason: "No policy matched - default allow".to_string(),
            policy_name: None,
            risk_score: 0.0,
            metadata: HashMap::new(),
        }
    }

    // Built-in policies
    pub fn no_dangerous_commands(action_type: &str, context: &HashMap<String, String>) -> Option<ActionDecision> {
        if action_type == "shell_command" {
            if let Some(cmd) = context.get("command") {
                let cmd_lower = cmd.to_lowercase();
                if cmd_lower.contains("rm -rf /") || cmd_lower.contains("format") || cmd_lower.contains("dd if=") {
                    return Some(ActionDecision {
                        decision: Decision::Block,
                        reason: format!("Dangerous command blocked: {}", cmd),
                        policy_name: Some("no_dangerous_commands".to_string()),
                        risk_score: 0.95,
                        metadata: HashMap::new(),
                    });
                }
            }
        }
        None
    }

    pub fn require_approval_for_network(action_type: &str, _context: &HashMap<String, String>) -> Option<ActionDecision> {
        if action_type == "network_request" || action_type == "http_request" {
            return Some(ActionDecision {
                decision: Decision::RequireApproval,
                reason: "Network access requires human approval".to_string(),
                policy_name: Some("require_approval_for_network".to_string()),
                risk_score: 0.6,
                metadata: HashMap::new(),
            });
        }
        None
    }

    pub fn block_write_outside_worktree(action_type: &str, context: &HashMap<String, String>) -> Option<ActionDecision> {
        if action_type == "file_write" {
            if let Some(path) = context.get("path") {
                if !path.contains("agentforge-") && !path.contains("/tmp/") {
                    return Some(ActionDecision {
                        decision: Decision::RequireApproval,
                        reason: "Write outside worktree requires approval".into(),
                        policy_name: Some("block_write_outside_worktree".into()),
                        risk_score: 0.7,
                        metadata: HashMap::new(),
                    });
                }
            }
        }
        None
    }
}

/// Convenience to build a default safe engine (matches Python create_default_approval_layer).
pub fn create_default_policy_engine() -> PolicyEngine {
    let mut eng = PolicyEngine::new();
    eng.add_rule(PolicyEngine::no_dangerous_commands);
    eng.add_rule(PolicyEngine::require_approval_for_network);
    eng.add_rule(PolicyEngine::block_write_outside_worktree);
    eng
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    #[test]
    fn default_policy_blocks_dangerous_rm() {
        let eng = create_default_policy_engine();
        let mut ctx = HashMap::new();
        ctx.insert("command".into(), "rm -rf /".into());
        let dec = eng.evaluate("shell_command", &ctx);
        assert_eq!(dec.decision, Decision::Block);
        assert!(dec.risk_score > 0.9);
    }

    #[test]
    fn default_allows_normal() {
        let eng = create_default_policy_engine();
        let ctx = HashMap::new();
        let dec = eng.evaluate("shell_command", &ctx);
        assert_eq!(dec.decision, Decision::Allow);
    }
}
