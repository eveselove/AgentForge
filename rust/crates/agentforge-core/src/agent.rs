use serde::{Deserialize, Serialize};
use std::sync::Arc;

/// Unique identifier for a swarm agent / task dispatcher target.
///
/// Switched to Arc<str> (from String) for cheap O(1) clones instead of O(n) allocations.
/// This is a targeted mitigation for clone bottlenecks in high-concurrency swarm paths:
/// - task lists / pending queues copied across threads
/// - claim/dispatch passing AgentId to many parallel workers (grok/antigravity/...)
/// - worktree metadata, trajectory records, HashMap keys in registries
///
/// Data structure is immutable by design; no interior mutability => no data races possible
/// (enforced by Rust + Arc's atomic refcount which is race-free for our use).
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct AgentId(Arc<str>);

impl serde::Serialize for AgentId {
    fn serialize<S: serde::Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        self.0.as_ref().serialize(s)
    }
}

impl<'de> serde::Deserialize<'de> for AgentId {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        let s = String::deserialize(d)?;
        Ok(AgentId::new(s))
    }
}

impl AgentId {
    pub fn new(name: impl Into<String>) -> Self {
        // Trim to defend against a common logical error: whitespace-only or padded IDs
        // coming from env/CLI/config/JSON (e.g. " grok ", "jules\n"). Silent trim here is safe
        // and prevents downstream key mismatches in stores, LanceDB, worktree dirs etc.
        let s = name.into().trim().to_owned();
        Self(Arc::from(s))
    }

    /// Borrowed view. Use this + AsRef instead of pub-tuple destructuring (encapsulation).
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl AsRef<str> for AgentId {
    fn as_ref(&self) -> &str {
        self.as_str()
    }
}

impl std::fmt::Display for AgentId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl From<String> for AgentId {
    fn from(s: String) -> Self {
        AgentId::new(s)
    }
}

impl From<&str> for AgentId {
    fn from(s: &str) -> Self {
        AgentId::new(s)
    }
}

impl PartialEq<str> for AgentId {
    fn eq(&self, other: &str) -> bool {
        self.0.as_ref() == other
    }
}

impl PartialEq<&str> for AgentId {
    fn eq(&self, other: &&str) -> bool {
        self.0.as_ref() == *other
    }
}

/// Agent descriptor for swarm registration, capability routing and dispatch decisions.
///
/// Added derives (PartialEq, Eq, Hash) so Agent values are usable as keys in HashSet/HashMap
/// (e.g. active_agents registry, dedup across tmux sessions / worktrees, coordination sets).
/// Previously missing => would have forced ad-hoc id-only hacks or runtime errors if someone
/// tried to use Agent directly for set membership in dispatcher/runner.
///
/// Capabilities: auto-deduped in ctors (logical error prevention: duplicate caps were possible,
/// leading to double-counting or incorrect "has_cap" results in routing).
///
/// All fields Clone+Send+Sync; the type itself introduces no shared mutable state and cannot
/// be the source of data races. Any races would be at store/claim level (see TaskStore::claim).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Hash)]
pub struct Agent {
    pub id: AgentId,
    pub name: String,
    pub capabilities: Vec<String>,
}

impl Agent {
    pub fn new(id: impl Into<AgentId>, name: impl Into<String>, capabilities: Vec<String>) -> Self {
        let caps = Self::dedup_caps(capabilities);
        Self {
            id: id.into(),
            name: name.into(),
            capabilities: caps,
        }
    }

    fn dedup_caps(caps: Vec<String>) -> Vec<String> {
        let mut seen = std::collections::HashSet::new();
        let mut out = Vec::with_capacity(caps.len());
        for c in caps {
            if seen.insert(c.clone()) {
                out.push(c);
            }
        }
        out
    }

    /// O(n) but n small (typically <10 caps). No alloc.
    pub fn has_capability(&self, cap: &str) -> bool {
        self.capabilities.iter().any(|c| c == cap)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn agent_id_and_struct() {
        let id = AgentId::new("grok");
        let a = Agent {
            id: id.clone(),
            name: "Grok".into(),
            capabilities: vec!["code".into()],
        };
        assert_eq!(a.id.as_str(), "grok");
        assert!(a.capabilities.contains(&"code".to_string()));
        assert!(a.has_capability("code"));
    }

    #[test]
    fn agent_id_newtype_ergonomics_and_trim() {
        let id: AgentId = "  grok  ".into();
        assert_eq!(id.as_str(), "grok");
        assert_eq!(id.to_string(), "grok");
        assert_eq!(id.to_string(), "grok");
        assert!(id == "grok");
        assert!(id == "grok" as &str);

        let a1 = AgentId::new("swarm-agent-42");
        let a2 = AgentId::new("swarm-agent-42");
        assert_eq!(a1, a2);
        // Arc clone is cheap (no deep copy) -- the point of the optimization
        let _clone1 = a1.clone();
        let _clone2 = a1.clone();
    }

    #[test]
    fn agent_new_dedups_caps_and_full_derives() {
        let ag = Agent::new(
            "swarm-leader",
            "Leader",
            vec![
                "code".into(),
                "code".into(),
                "review".into(),
                "dispatch".into(),
                "review".into(),
            ],
        );
        assert_eq!(ag.capabilities.len(), 3);
        assert!(ag.has_capability("dispatch"));
        assert!(!ag.has_capability("nonexistent"));

        // Now usable in sets thanks to Hash/Eq derive (prevents ad-hoc bugs in swarm mgmt)
        let mut registry: std::collections::HashSet<Agent> = std::collections::HashSet::new();
        registry.insert(ag.clone());
        registry.insert(ag.clone()); // dup
        assert_eq!(registry.len(), 1);
        assert!(registry.contains(&ag));

        // Agent equality based on all fields (incl caps after dedup)
        let ag2 = Agent::new(
            "swarm-leader",
            "Leader",
            vec!["code".into(), "review".into(), "dispatch".into()],
        );
        assert_eq!(ag, ag2);
    }
}
