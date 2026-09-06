use async_trait::async_trait;
use futures_util::stream::{BoxStream, StreamExt};
use reqwest::Client;
use serde_json::json;

use crate::ai::providers::types::{GenerateRequest, GenerateResponse, GenerateStreamChunk, TokenUsage};
use crate::ai::providers::{AIProvider, ProviderError};

pub struct OllamaProvider {
    model: String,
    url: String,
    client: Client,
}

impl OllamaProvider {
    pub fn new(model: String, url: String) -> Self {
        Self {
            model,
            url: url.trim_end_matches('/').to_string(),
            client: Client::new(),
        }
    }
}

#[async_trait]
impl AIProvider for OllamaProvider {
    fn name(&self) -> &'static str {
        "Ollama"
    }

    async fn generate(&self, request: &GenerateRequest) -> Result<GenerateResponse, ProviderError> {
        let endpoint = format!("{}/api/generate", self.url);

        let mut body = json!({
            "model": self.model,
            "prompt": request.prompt,
            "stream": false,
            "options": {
                "temperature": request.temperature.unwrap_or(0.7),
                "num_predict": request.max_tokens.unwrap_or(2048)
            }
        });

        if let Some(sys) = &request.system_prompt {
            body["system"] = json!(sys);
        }

        if let Some(images) = &request.images {
            if !images.is_empty() {
                body["images"] = json!(images);
            }
        }

        let res = self.client.post(&endpoint).json(&body).send().await?;

        if !res.status().is_success() {
            let status = res.status();
            let err_text = res.text().await.unwrap_or_default();
            return Err(ProviderError::ApiError(format!(
                "Ollama HTTP {} - {}",
                status, err_text
            )));
        }

        let json_res: serde_json::Value = res.json().await?;
        let text = json_res["response"].as_str().unwrap_or("").to_string();

        let usage = if json_res["done"].as_bool().unwrap_or(false) {
            let prompt_tokens = json_res["prompt_eval_count"].as_u64().unwrap_or(0) as u32;
            let completion_tokens = json_res["eval_count"].as_u64().unwrap_or(0) as u32;
            Some(TokenUsage {
                prompt_tokens,
                completion_tokens,
                total_tokens: prompt_tokens + completion_tokens,
            })
        } else {
            None
        };

        Ok(GenerateResponse {
            text,
            usage,
            metadata: Some(json_res),
        })
    }

    async fn generate_stream(
        &self,
        request: &GenerateRequest,
    ) -> Result<BoxStream<'static, Result<GenerateStreamChunk, ProviderError>>, ProviderError> {
        let endpoint = format!("{}/api/generate", self.url);

        let mut body = json!({
            "model": self.model,
            "prompt": request.prompt,
            "stream": true,
            "options": {
                "temperature": request.temperature.unwrap_or(0.7),
                "num_predict": request.max_tokens.unwrap_or(2048)
            }
        });

        if let Some(sys) = &request.system_prompt {
            body["system"] = json!(sys);
        }

        if let Some(images) = &request.images {
            if !images.is_empty() {
                body["images"] = json!(images);
            }
        }

        let res = self.client.post(&endpoint).json(&body).send().await?;

        if !res.status().is_success() {
            let status = res.status();
            let err_text = res.text().await.unwrap_or_default();
            return Err(ProviderError::ApiError(format!(
                "Ollama HTTP {} - {}",
                status, err_text
            )));
        }

        let stream = res.bytes_stream().map(|chunk_res| match chunk_res {
            Ok(bytes) => {
                let s = String::from_utf8_lossy(&bytes);
                let mut chunks = Vec::new();
                for line in s.lines() {
                    let trimmed = line.trim();
                    if trimmed.is_empty() {
                        continue;
                    }
                    if let Ok(json_res) = serde_json::from_str::<serde_json::Value>(trimmed) {
                        let text = json_res["response"].as_str().unwrap_or("").to_string();
                        let is_finished = json_res["done"].as_bool();
                        let usage = if is_finished.unwrap_or(false) {
                            let prompt_tokens = json_res["prompt_eval_count"].as_u64().unwrap_or(0) as u32;
                            let completion_tokens = json_res["eval_count"].as_u64().unwrap_or(0) as u32;
                            Some(TokenUsage {
                                prompt_tokens,
                                completion_tokens,
                                total_tokens: prompt_tokens + completion_tokens,
                            })
                        } else {
                            None
                        };

                        chunks.push(Ok(GenerateStreamChunk {
                            text,
                            is_finished,
                            usage,
                            metadata: Some(json_res),
                        }));
                    }
                }
                futures_util::stream::iter(chunks)
            }
            Err(e) => {
                futures_util::stream::iter(vec![Err(ProviderError::NetworkError(e))])
            }
        }).flatten();

        Ok(Box::pin(stream))
    }
}
