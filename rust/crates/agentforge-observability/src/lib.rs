//! AgentForge Observability (Phase 1/3) - Span, Trace, replay, OTEL-shaped export + PRM binding.
//! Mirrors Python agentforge/observability/spans.py + replay.py

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpanContext {
    pub trace_id: String,
    pub span_id: String,
    pub parent_span_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Span {
    pub name: String,
    pub context: SpanContext,
    pub start_time: DateTime<Utc>,
    pub end_time: Option<DateTime<Utc>>,
    pub attributes: HashMap<String, serde_json::Value>,
    pub events: Vec<serde_json::Value>,
    pub status: String, // unset, ok, error
    pub prm_score: Option<f64>,
}

impl Span {
    pub fn new(name: &str) -> Self {
        let trace_id = Uuid::new_v4().to_string();
        Self {
            name: name.to_string(),
            context: SpanContext {
                trace_id: trace_id.clone(),
                span_id: Uuid::new_v4().to_string(),
                parent_span_id: None,
            },
            start_time: Utc::now(),
            end_time: None,
            attributes: HashMap::new(),
            events: Vec::new(),
            status: "unset".to_string(),
            prm_score: None,
        }
    }

    pub fn add_event(&mut self, name: &str, attrs: Option<HashMap<String, serde_json::Value>>) {
        self.events.push(serde_json::json!({
            "name": name,
            "timestamp": Utc::now().to_rfc3339(),
            "attributes": attrs.unwrap_or_default()
        }));
    }

    pub fn set_attribute(&mut self, key: &str, val: serde_json::Value) {
        self.attributes.insert(key.to_string(), val);
    }

    pub fn attach_prm(&mut self, score: f64, notes: Option<String>) {
        self.prm_score = Some(score);
        if let Some(n) = notes {
            self.set_attribute("prm_notes", serde_json::json!(n));
        }
    }

    pub fn finish(&mut self) {
        self.end_time = Some(Utc::now());
        if self.status == "unset" {
            self.status = "ok".to_string();
        }
    }

    pub fn to_otel_like(&self) -> serde_json::Value {
        serde_json::json!({
            "resourceSpans": [{
                "resource": {"service.name": "agentforge"},
                "scopeSpans": [{
                    "spans": [{
                        "traceId": self.context.trace_id,
                        "spanId": self.context.span_id,
                        "parentSpanId": self.context.parent_span_id,
                        "name": self.name,
                        "startTime": self.start_time.to_rfc3339(),
                        "endTime": self.end_time.map(|e| e.to_rfc3339()),
                        "attributes": self.attributes,
                        "events": self.events,
                        "status": {"code": self.status},
                        "prm_score": self.prm_score
                    }]
                }]
            }]
        })
    }
}

/// Replay a trajectory (list of events) into spans, optionally attaching PRM labels.
pub fn replay_trajectory_to_spans(
    task_id: &str,
    events: &[serde_json::Value],
    prm_overall: Option<f64>,
) -> Vec<Span> {
    let mut spans = Vec::new();
    let mut current = Span::new(&format!("task_{}", task_id));
    current.set_attribute("task_id", serde_json::json!(task_id));

    for (i, ev) in events.iter().enumerate() {
        let etype = ev.get("type").and_then(|v| v.as_str()).unwrap_or("event");
        current.add_event(
            etype,
            Some({
                let mut m = HashMap::new();
                m.insert("raw".to_string(), ev.clone());
                m
            }),
        );
        if i % 4 == 0 && i > 0 {
            current.finish();
            spans.push(current.clone());
            current = Span::new(&format!("phase_{}", i / 4));
        }
    }
    current.finish();
    if let Some(p) = prm_overall {
        current.attach_prm(p, Some("replayed".into()));
    }
    spans.push(current);
    spans
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn span_lifecycle_and_prm() {
        let mut s = Span::new("test_op");
        s.add_event("tool_call", None);
        s.attach_prm(0.82, Some("good recovery".into()));
        s.finish();
        assert!(s.prm_score.is_some());
        let otel = s.to_otel_like();
        assert!(otel["resourceSpans"].is_array());
    }
}
