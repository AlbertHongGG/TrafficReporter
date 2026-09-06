use chrono::Local;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::PathBuf;

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct AgentLogMetadata {
    pub agent_name: String,
    pub provider: String,
    pub model: String,
    pub execution_time_ms: u64,
    pub timestamp: String,
    #[serde(flatten)]
    pub extra: Option<Value>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct AgentLogEntry {
    pub request: Value,
    pub respond: Value,
    pub metadata: AgentLogMetadata,
}

pub struct AgentLogger;

impl AgentLogger {
    pub fn resolve_runtime_logs_dir() -> PathBuf {
        let current_dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        let project_root = if current_dir.ends_with("src-tauri") {
            current_dir.parent().unwrap_or(&current_dir).to_path_buf()
        } else {
            current_dir
        };
        project_root.join(".runtime").join("logs")
    }

    pub fn log(
        agent_name: &str,
        provider: &str,
        model: &str,
        execution_time_ms: u64,
        request: Value,
        respond: Value,
        extra_metadata: Option<Value>,
    ) -> Result<PathBuf, std::io::Error> {
        let logs_dir = Self::resolve_runtime_logs_dir();
        std::fs::create_dir_all(&logs_dir)?;

        let now = Local::now();
        let timestamp = now.format("%Y%m%d_%H%M%S").to_string();
        let nanos = now.timestamp_subsec_nanos();
        let random_id = format!("{:06x}", nanos % 0xFFFFFF);

        let file_name = format!("{}_{}_{}.json", timestamp, agent_name, random_id);
        let file_path = logs_dir.join(file_name);

        let parsed_respond: Value = if let Some(s) = respond.as_str() {
            serde_json::from_str(s).unwrap_or(respond)
        } else {
            respond
        };

        let entry = AgentLogEntry {
            request,
            respond: parsed_respond,
            metadata: AgentLogMetadata {
                agent_name: agent_name.to_string(),
                provider: provider.to_string(),
                model: model.to_string(),
                execution_time_ms,
                timestamp: now.to_rfc3339(),
                extra: extra_metadata,
            },
        };

        let file = std::fs::File::create(&file_path)?;
        serde_json::to_writer_pretty(file, &entry)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;

        Ok(file_path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_agent_logger_writes_valid_json() {
        let req = json!({ "prompt": "Hello", "systemPrompt": "You are a test agent" });
        let resp = json!({ "text": "World" });
        let res = AgentLogger::log(
            "TestAgent",
            "mock_provider",
            "mock_model",
            123,
            req,
            resp,
            Some(json!({ "testKey": "testVal" })),
        );

        assert!(res.is_ok());
        let path = res.unwrap();
        assert!(path.exists());
        let content = std::fs::read_to_string(&path).unwrap();
        let parsed: Value = serde_json::from_str(&content).unwrap();

        assert_eq!(parsed["metadata"]["agentName"], "TestAgent");
        assert_eq!(parsed["metadata"]["executionTimeMs"], 123);
        assert_eq!(parsed["metadata"]["provider"], "mock_provider");
        assert_eq!(parsed["request"]["prompt"], "Hello");
        assert_eq!(parsed["respond"]["text"], "World");

        // Clean up test file
        let _ = std::fs::remove_file(path);
    }
}
