#[cfg(test)]
mod tests {
    use std::sync::Arc;
    use async_trait::async_trait;
    use futures_util::stream::BoxStream;
    use serde_json::{json, Value};

    use crate::ai::agents::{AgentError, AgentFactory, AgentType};
    use crate::ai::logger::AgentLogger;
    use crate::ai::providers::types::{GenerateRequest, GenerateResponse, GenerateStreamChunk};
    use crate::ai::providers::{AIProvider, ProviderError, ProviderFactory};

    struct MockAIProvider {
        response_text: String,
        should_fail: bool,
    }

    impl MockAIProvider {
        fn new(response_text: &str) -> Self {
            Self {
                response_text: response_text.to_string(),
                should_fail: false,
            }
        }

        fn new_failing() -> Self {
            Self {
                response_text: String::new(),
                should_fail: true,
            }
        }
    }

    #[async_trait]
    impl AIProvider for MockAIProvider {
        fn name(&self) -> &'static str {
            "MockProvider"
        }

        async fn generate(&self, _request: &GenerateRequest) -> Result<GenerateResponse, ProviderError> {
            if self.should_fail {
                return Err(ProviderError::ApiError("Mock failure".to_string()));
            }
            Ok(GenerateResponse {
                text: self.response_text.clone(),
                usage: None,
                metadata: Some(json!({ "mock": true })),
            })
        }

        async fn generate_stream(
            &self,
            _request: &GenerateRequest,
        ) -> Result<BoxStream<'static, Result<GenerateStreamChunk, ProviderError>>, ProviderError> {
            Err(ProviderError::ApiError("Not implemented".to_string()))
        }
    }

    #[test]
    fn test_provider_factory_supported_types() {
        // Ollama
        let ollama = ProviderFactory::create_provider("ollama", "qwen", Some("http://localhost:11434"));
        assert!(ollama.is_ok());
        assert_eq!(ollama.unwrap().name(), "Ollama");

        // GeminiFlow
        let gemini = ProviderFactory::create_provider("geminiflow", "gemini-3-pro", Some("http://localhost:8000"));
        assert!(gemini.is_ok());
        assert_eq!(gemini.unwrap().name(), "GeminiFlow");

        // Unsupported
        let invalid = ProviderFactory::create_provider("unsupported_provider", "model", None);
        assert!(invalid.is_err());
    }

    #[test]
    fn test_agent_logger_file_format_and_metadata() {
        let req = json!({ "prompt": "Identify target vehicle" });
        let resp = json!({ "selectedTrackId": "track-123", "confidence": 0.95 });
        let log_res = AgentLogger::log(
            "TestResolutionAgent",
            "MockProvider",
            "test-model",
            450,
            req,
            resp,
            Some(json!({ "customTag": "vNext" })),
        );

        assert!(log_res.is_ok());
        let log_path = log_res.unwrap();
        assert!(log_path.exists());

        let file_name = log_path.file_name().unwrap().to_str().unwrap();
        // File name format: YYYYMMDD_HHMMSS_<agent_name>_<random_id>.json
        assert!(file_name.contains("TestResolutionAgent"));
        assert!(file_name.ends_with(".json"));

        let content = std::fs::read_to_string(&log_path).unwrap();
        let parsed: Value = serde_json::from_str(&content).unwrap();

        assert_eq!(parsed["metadata"]["agentName"], "TestResolutionAgent");
        assert_eq!(parsed["metadata"]["provider"], "MockProvider");
        assert_eq!(parsed["metadata"]["model"], "test-model");
        assert_eq!(parsed["metadata"]["executionTimeMs"], 450);
        assert_eq!(parsed["metadata"]["customTag"], "vNext");
        assert_eq!(parsed["respond"]["selectedTrackId"], "track-123");

        // Cleanup
        let _ = std::fs::remove_file(log_path);
    }

    #[tokio::test]
    async fn test_coarse_localization_agent_execution() {
        let mock_json = r#"{
            "startFrameId": "frame_001",
            "endFrameId": "frame_050",
            "anchorFrameId": "frame_025",
            "summary": "車輛於路口左轉"
        }"#;
        let provider = Arc::new(MockAIProvider::new(mock_json));
        let agent = AgentFactory::create_agent(
            AgentType::CoarseLocalization,
            provider,
            "mock-model".to_string(),
        );

        assert_eq!(agent.name(), "CoarseLocalizationAgent");

        let input = json!({
            "description": "銀色自小客車左轉",
            "frameList": "frame_001, frame_025, frame_050",
            "images": []
        });

        let result = agent.execute(input).await;
        assert!(result.is_ok());
        let val = result.unwrap();
        assert_eq!(val["startFrameId"], "frame_001");
        assert_eq!(val["endFrameId"], "frame_050");
        assert_eq!(val["anchorFrameId"], "frame_025");
    }

    #[tokio::test]
    async fn test_fine_localization_agent_execution_with_markdown_strip() {
        let mock_json = "```json\n{\n\"startFrameId\": \"frame_010\",\n\"endFrameId\": \"frame_040\",\n\"anchorFrameId\": \"frame_025\",\n\"summary\": \"銀色車輛切入車道\",\n\"keyframeCountReason\": null,\n\"keyframes\": [{\"frameId\": \"frame_025\", \"description\": \"車頭進入\"}]\n}\n```";
        let provider = Arc::new(MockAIProvider::new(mock_json));
        let agent = AgentFactory::create_agent(
            AgentType::FineLocalization,
            provider,
            "mock-model".to_string(),
        );

        assert_eq!(agent.name(), "FineLocalizationAgent");

        let input = json!({
            "description": "銀色車輛切入車道",
            "frameList": "frame_010..frame_040",
            "maxKeyframes": 8
        });

        let result = agent.execute(input).await;
        assert!(result.is_ok());
        let val = result.unwrap();
        assert_eq!(val["startFrameId"], "frame_010");
        assert_eq!(val["keyframes"].as_array().unwrap().len(), 1);
    }

    #[tokio::test]
    async fn test_target_resolution_agent_execution() {
        let mock_json = r#"{
            "selectedTrackId": "trk-777",
            "selectedCandidateId": "ABC-1234",
            "confidence": 0.98,
            "plateHintConsistency": "supporting",
            "rationale": "車型與車牌號碼完全相符"
        }"#;
        let provider = Arc::new(MockAIProvider::new(mock_json));
        let agent = AgentFactory::create_agent(
            AgentType::TargetResolution,
            provider,
            "mock-model".to_string(),
        );

        assert_eq!(agent.name(), "TargetResolutionAgent");

        let input = json!({
            "promptPayload": {
                "description": "白色休旅車 ABC-1234",
                "candidates": ["ABC-1234"]
            }
        });

        let result = agent.execute(input).await;
        assert!(result.is_ok());
        let val = result.unwrap();
        assert_eq!(val["selectedTrackId"], "trk-777");
        assert_eq!(val["confidence"], 0.98);
        assert_eq!(val["plateHintConsistency"], "supporting");
    }

    #[tokio::test]
    async fn test_agent_error_handling_on_provider_failure() {
        let provider = Arc::new(MockAIProvider::new_failing());
        let agent = AgentFactory::create_agent(
            AgentType::CoarseLocalization,
            provider,
            "mock-model".to_string(),
        );

        let input = json!({
            "description": "任何描述"
        });

        let result = agent.execute(input).await;
        assert!(result.is_err());
        match result.unwrap_err() {
            AgentError::Provider(_) => {}
            other => panic!("Expected AgentError::Provider, got {:?}", other),
        }
    }

    #[test]
    fn test_resolve_default_provider() {
        let res = crate::ai::workflow::AiEvidenceWorkflowEngine::resolve_default_provider();
        assert!(res.is_ok());
        let (provider, model) = res.unwrap();
        assert_eq!(provider.name(), "Ollama");
        assert!(!model.is_empty());
    }
}
