//! CandidateStore FS implementation (skeleton).
//! Full: _candidate_subdir_name, meta merge from rich export, symlink support, etc.

use super::*;
// use std::path::Path;  // enable when real FS logic added

pub struct StoreImpl; // placeholder for expansion

impl CandidateStore {
    /// Placeholder for richer listing with prioritization hooks.
    pub fn list_high_value(&self, min_high_value: u64) -> Vec<CandidateSummary> {
        self.list_pending()
            .unwrap_or_default()
            .into_iter()
            .filter(|c| c.high_value_count >= min_high_value && !c.promoted)
            .collect()
    }
}
