use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Hash)]
pub struct AgentId(pub String);

impl AgentId {
    pub fn new(name: impl Into<String>) -> Self {
        Self(name.into())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Agent {
    pub id: AgentId,
    pub name: String,
    pub capabilities: Vec<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn agent_id_and_struct() {
        let id = AgentId::new("grok");
        let a = Agent { id: id.clone(), name: "Grok".into(), capabilities: vec!["code".into()] };
        assert_eq!(a.id.0, "grok");
        assert!(a.capabilities.contains(&"code".to_string()));
    }
}
