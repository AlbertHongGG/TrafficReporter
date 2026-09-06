pub mod prompts;

use async_trait::async_trait;
use serde_json::{json, Value};
use std::sync::Arc;
use std::time::Instant;

use crate::ai::agents::{Agent, AgentError};
use crate::ai::logger::AgentLogger;
use crate::ai::providers::types::GenerateRequest;
use crate::ai::providers::AIProvider;

pub struct TargetResolutionAgent {
    provider: Arc<dyn AIProvider>,
    model: String,
}

impl TargetResolutionAgent {
    pub fn new(provider: Arc<dyn AIProvider>, model: String) -> Self {
        Self { provider, model }
    }

    fn clean_json_string(raw: &str) -> &str {
        let mut text = raw.trim();
        if text.starts_with("```json") {
            text = &text[7..];
        } else if text.starts_with("```") {
            text = &text[3..];
        }
        if text.ends_with("```") {
            text = &text[..text.len() - 3];
        }
        text.trim()
    }
}

#[async_trait]
impl Agent for TargetResolutionAgent {
    fn name(&self) -> &'static str {
        "TargetResolutionAgent"
    }

    async fn execute(&self, input: Value) -> Result<Value, AgentError> {
        let prompt_payload = input
            .get("promptPayload")
            .cloned()
            .unwrap_or_else(|| input.clone());

        let payload_str = serde_json::to_string_pretty(&prompt_payload)
            .map_err(|e| AgentError::InvalidInput(format!("Payload serialization failed: {}", e)))?;

        let images: Option<Vec<String>> = input.get("images").and_then(|v| {
            v.as_array().map(|arr| {
                arr.iter()
                    .filter_map(|item| item.as_str().map(|s| s.to_string()))
                    .collect()
            })
        });

        let system_prompt = prompts::build_system_prompt().to_string();
        let prompt = prompts::build_user_prompt(&payload_str);

        let request = GenerateRequest {
            prompt: prompt.clone(),
            system_prompt: Some(system_prompt.clone()),
            messages: None,
            temperature: Some(0.2),
            max_tokens: Some(1024),
            images: images.clone(),
            session_id: input.get("sessionId").and_then(|v| v.as_str()).map(|s| s.to_string()),
            stream: Some(false),
        };

        let request_log_payload = json!({
            "prompt": prompt,
            "systemPrompt": system_prompt,
            "imageCount": images.as_ref().map(|imgs| imgs.len()).unwrap_or(0),
        });

        let start_time = Instant::now();
        let generate_result = self.provider.generate(&request).await;
        let execution_time_ms = start_time.elapsed().as_millis() as u64;

        match generate_result {
            Ok(response) => {
                let cleaned_text = Self::clean_json_string(&response.text);
                let parsed_result: Value = match serde_json::from_str(cleaned_text) {
                    Ok(val) => val,
                    Err(e) => {
                        let _ = AgentLogger::log(
                            self.name(),
                            self.provider.name(),
                            &self.model,
                            execution_time_ms,
                            request_log_payload,
                            json!({ "raw": response.text, "error": e.to_string() }),
                            Some(json!({ "status": "json_parse_error" })),
                        );
                        return Err(AgentError::InvalidOutput(format!(
                            "Failed to parse LLM JSON: {}",
                            e
                        )));
                    }
                };

                let _ = AgentLogger::log(
                    self.name(),
                    self.provider.name(),
                    &self.model,
                    execution_time_ms,
                    request_log_payload,
                    parsed_result.clone(),
                    Some(json!({ "status": "succeeded" })),
                );

                Ok(parsed_result)
            }
            Err(e) => {
                let _ = AgentLogger::log(
                    self.name(),
                    self.provider.name(),
                    &self.model,
                    execution_time_ms,
                    request_log_payload,
                    json!({ "error": e.to_string() }),
                    Some(json!({ "status": "failed" })),
                );
                Err(AgentError::Provider(e))
            }
        }
    }
}
