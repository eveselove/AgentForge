use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum Outcome {
    Success,
    Failure,
    PartialSuccess,
    Timeout,
    Cancelled,
}

impl Outcome {
    pub fn is_success(&self) -> bool {
        matches!(self, Outcome::Success | Outcome::PartialSuccess)
    }

    pub fn is_failure(&self) -> bool {
        matches!(self, Outcome::Failure | Outcome::Timeout | Outcome::Cancelled)
    }
}

impl std::fmt::Display for Outcome {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = match self {
            Outcome::Success => "success",
            Outcome::Failure => "failure",
            Outcome::PartialSuccess => "partial_success",
            Outcome::Timeout => "timeout",
            Outcome::Cancelled => "cancelled",
        };
        write!(f, "{}", s)
    }
}

/// Error for strict parsing (use `Outcome::from("foo")` for lenient fallback to Failure).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParseOutcomeError(pub String);

impl std::fmt::Display for ParseOutcomeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "invalid outcome string: {}", self.0)
    }
}

impl std::error::Error for ParseOutcomeError {}

impl std::str::FromStr for Outcome {
    type Err = ParseOutcomeError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "success" | "succeeded" | "ok" => Ok(Outcome::Success),
            "failed" | "failure" | "fail" => Ok(Outcome::Failure),
            "partial" | "partial_success" => Ok(Outcome::PartialSuccess),
            "timeout" => Ok(Outcome::Timeout),
            "cancelled" | "canceled" => Ok(Outcome::Cancelled),
            _ => Err(ParseOutcomeError(s.to_string())),
        }
    }
}

/// Lenient From<&str>: unknown -> Failure (matches historical Python/JSON interop behavior).
impl From<&str> for Outcome {
    fn from(s: &str) -> Self {
        s.parse().unwrap_or(Outcome::Failure)
    }
}

impl From<String> for Outcome {
    fn from(s: String) -> Self {
        Outcome::from(s.as_str())
    }
}

/// Convenience: Outcome -> String via Display.
impl From<Outcome> for String {
    fn from(o: Outcome) -> Self {
        o.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn outcome_success_variants() {
        assert!(Outcome::Success.is_success());
        assert!(Outcome::PartialSuccess.is_success());
        assert!(!Outcome::Failure.is_success());
        assert!(!Outcome::Timeout.is_success());
    }

    #[test]
    fn outcome_failure_variants() {
        assert!(Outcome::Failure.is_failure());
        assert!(Outcome::Timeout.is_failure());
        assert!(Outcome::Cancelled.is_failure());
        assert!(!Outcome::Success.is_failure());
        assert!(!Outcome::PartialSuccess.is_failure());
    }

    #[test]
    fn outcome_display() {
        assert_eq!(Outcome::PartialSuccess.to_string(), "partial_success");
        assert_eq!(format!("{}", Outcome::Failure), "failure");
    }

    #[test]
    fn outcome_serde_roundtrip_all_variants() {
        let variants = [
            Outcome::Success,
            Outcome::Failure,
            Outcome::PartialSuccess,
            Outcome::Timeout,
            Outcome::Cancelled,
        ];
        for v in &variants {
            let json = serde_json::to_string(v).expect("serialize");
            let back: Outcome = serde_json::from_str(&json).expect("deserialize");
            assert_eq!(*v, back);
            // also via Value for interop
            let val = serde_json::to_value(v).unwrap();
            let back2: Outcome = serde_json::from_value(val).unwrap();
            assert_eq!(*v, back2);
        }
    }

    #[test]
    fn outcome_from_str_and_from_lenient() {
        use std::str::FromStr;
        assert_eq!(Outcome::from_str("success").unwrap(), Outcome::Success);
        assert_eq!(Outcome::from_str("Partial_Success").unwrap(), Outcome::PartialSuccess);
        assert_eq!(Outcome::from_str("TIMEOUT").unwrap(), Outcome::Timeout);
        assert!(Outcome::from_str("nonsense").is_err());

        // Lenient From
        assert_eq!(Outcome::from("failed"), Outcome::Failure);
        assert_eq!(Outcome::from("weird-unknown-xyz"), Outcome::Failure);
        assert_eq!(Outcome::from("ok"), Outcome::Success);
        assert_eq!(Outcome::from(String::from("cancelled")), Outcome::Cancelled);

        // Roundtrip via From<String>
        let s: String = Outcome::PartialSuccess.into();
        assert_eq!(s, "partial_success");
        let back: Outcome = s.into();
        assert_eq!(back, Outcome::PartialSuccess);
    }
}
