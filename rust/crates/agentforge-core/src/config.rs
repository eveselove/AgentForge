use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentForgeConfig {
    pub data_dir: String,
    pub trajectories_dir: String,
    pub max_concurrent_tasks: usize,
    pub default_agent: String,
}

impl Default for AgentForgeConfig {
    fn default() -> Self {
        Self {
            data_dir: "./data".to_string(),
            trajectories_dir: "./data/trajectories".to_string(),
            max_concurrent_tasks: 4,
            default_agent: "grok".to_string(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn config_default_values() {
        let c = AgentForgeConfig::default();
        assert_eq!(c.max_concurrent_tasks, 4);
        assert_eq!(c.default_agent, "grok");
        assert!(c.data_dir.contains("data"));
    }
}
