pub mod types;
pub mod geminiflow;
pub mod ollama;
pub mod vertexai;

use async_trait::async_trait;
use futures_util::stream::BoxStream;
use std::sync::Arc;

pub use types::{GenerateRequest, GenerateResponse, GenerateStreamChunk, TokenUsage};

#[derive(Debug, thiserror::Error)]
pub enum ProviderError {
    #[error("Configuration Error: {0}")]
    ConfigError(String),
    #[error("Network Error: {0}")]
    NetworkError(#[from] reqwest::Error),
    #[error("API Error: {0}")]
    ApiError(String),
    #[error("JSON Error: {0}")]
    JsonError(#[from] serde_json::Error),
    #[error("Timeout Error: {0}")]
    TimeoutError(String),
}

#[async_trait]
pub trait AIProvider: Send + Sync {
    fn name(&self) -> &'static str;
    async fn generate(&self, request: &GenerateRequest) -> Result<GenerateResponse, ProviderError>;
    async fn generate_stream(
        &self,
        request: &GenerateRequest,
    ) -> Result<BoxStream<'static, Result<GenerateStreamChunk, ProviderError>>, ProviderError>;
}

pub struct ProviderFactory;

impl ProviderFactory {
    pub fn create_provider(
        provider_type: &str,
        model: &str,
        custom_url: Option<&str>,
    ) -> Result<Arc<dyn AIProvider>, ProviderError> {
        match provider_type.to_lowercase().as_str() {
            "geminiflow" => {
                let url = custom_url
                    .map(|s| s.to_string())
                    .or_else(|| std::env::var("TRAFFIC_GEMINIFLOW_URL").ok())
                    .or_else(|| std::env::var("PROVIDER_GEMINIFLOW_URL").ok())
                    .unwrap_or_else(|| "http://127.0.0.1:8000".to_string());
                Ok(Arc::new(geminiflow::GeminiFlowProvider::new(
                    model.to_string(),
                    url,
                )))
            }
            "ollama" => {
                let url = custom_url
                    .map(|s| s.to_string())
                    .or_else(|| std::env::var("TRAFFIC_OLLAMA_URL").ok())
                    .or_else(|| std::env::var("PROVIDER_OLLAMA_URL").ok())
                    .unwrap_or_else(|| "http://127.0.0.1:11434".to_string());
                Ok(Arc::new(ollama::OllamaProvider::new(
                    model.to_string(),
                    url,
                )))
            }
            "vertex" | "vertexai" => {
                let project_id = std::env::var("PROVIDER_VERTEX_PROJECT_ID")
                    .or_else(|_| std::env::var("VERTEX_PROJECT_ID"))
                    .map_err(|_| ProviderError::ConfigError("Missing PROVIDER_VERTEX_PROJECT_ID in env".into()))?;
                let region = std::env::var("PROVIDER_VERTEX_REGION")
                    .or_else(|_| std::env::var("VERTEX_REGION"))
                    .unwrap_or_else(|_| "us-central1".to_string());
                let access_token = std::env::var("PROVIDER_VERTEX_ACCESS_TOKEN")
                    .or_else(|_| std::env::var("VERTEX_ACCESS_TOKEN"))
                    .unwrap_or_default();

                Ok(Arc::new(vertexai::VertexAIProvider::new(
                    model.to_string(),
                    project_id,
                    region,
                    access_token,
                )))
            }
            _ => Err(ProviderError::ConfigError(format!(
                "Unsupported AI provider type: '{}'",
                provider_type
            ))),
        }
    }
}
