use async_trait::async_trait;
use eventsource_stream::Eventsource;
use futures_util::stream::{BoxStream, StreamExt};
use reqwest::Client;
use serde_json::json;

use crate::ai::providers::types::{GenerateRequest, GenerateResponse, GenerateStreamChunk, TokenUsage};
use crate::ai::providers::{AIProvider, ProviderError};

pub struct VertexAIProvider {
    model: String,
    project_id: String,
    region: String,
    access_token: String,
    client: Client,
}

impl VertexAIProvider {
    pub fn new(model: String, project_id: String, region: String, access_token: String) -> Self {
        Self {
            model,
            project_id,
            region,
            access_token,
            client: Client::new(),
        }
    }

    fn build_endpoint(&self, stream: bool) -> String {
        let action = if stream {
            "streamGenerateContent?alt=sse"
        } else {
            "generateContent"
        };
        format!(
            "https://{}-aiplatform.googleapis.com/v1/projects/{}/locations/{}/publishers/google/models/{}:{}",
            self.region, self.project_id, self.region, self.model, action
        )
    }
}

#[async_trait]
impl AIProvider for VertexAIProvider {
    fn name(&self) -> &'static str {
        "VertexAI"
    }

    async fn generate(&self, request: &GenerateRequest) -> Result<GenerateResponse, ProviderError> {
        let endpoint = self.build_endpoint(false);

        let mut parts = Vec::new();
        parts.push(json!({ "text": request.prompt }));

        if let Some(images) = &request.images {
            for img in images {
                parts.push(json!({
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": img
                    }
                }));
            }
        }

        let mut body = json!({
            "contents": [{
                "role": "user",
                "parts": parts
            }],
            "generationConfig": {
                "temperature": request.temperature.unwrap_or(0.2),
                "maxOutputTokens": request.max_tokens.unwrap_or(2048)
            }
        });

        if let Some(sys) = &request.system_prompt {
            body["systemInstruction"] = json!({
                "role": "system",
                "parts": [{ "text": sys }]
            });
        }

        let mut req_builder = self.client.post(&endpoint).json(&body);
        if !self.access_token.is_empty() {
            req_builder = req_builder.bearer_auth(&self.access_token);
        }

        let res = req_builder.send().await?;

        if !res.status().is_success() {
            let status = res.status();
            let err_text = res.text().await.unwrap_or_default();
            return Err(ProviderError::ApiError(format!(
                "VertexAI HTTP {} - {}",
                status, err_text
            )));
        }

        let json_res: serde_json::Value = res.json().await?;
        let text = json_res["candidates"][0]["content"]["parts"][0]["text"]
            .as_str()
            .unwrap_or("")
            .to_string();

        let usage = json_res.get("usageMetadata").map(|u| TokenUsage {
            prompt_tokens: u["promptTokenCount"].as_u64().unwrap_or(0) as u32,
            completion_tokens: u["candidatesTokenCount"].as_u64().unwrap_or(0) as u32,
            total_tokens: u["totalTokenCount"].as_u64().unwrap_or(0) as u32,
        });

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
        let endpoint = self.build_endpoint(true);

        let mut parts = Vec::new();
        parts.push(json!({ "text": request.prompt }));

        if let Some(images) = &request.images {
            for img in images {
                parts.push(json!({
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": img
                    }
                }));
            }
        }

        let mut body = json!({
            "contents": [{
                "role": "user",
                "parts": parts
            }],
            "generationConfig": {
                "temperature": request.temperature.unwrap_or(0.2),
                "maxOutputTokens": request.max_tokens.unwrap_or(2048)
            }
        });

        if let Some(sys) = &request.system_prompt {
            body["systemInstruction"] = json!({
                "role": "system",
                "parts": [{ "text": sys }]
            });
        }

        let mut req_builder = self.client.post(&endpoint).json(&body);
        if !self.access_token.is_empty() {
            req_builder = req_builder.bearer_auth(&self.access_token);
        }

        let res = req_builder.send().await?;

        if !res.status().is_success() {
            let status = res.status();
            let err_text = res.text().await.unwrap_or_default();
            return Err(ProviderError::ApiError(format!(
                "VertexAI HTTP {} - {}",
                status, err_text
            )));
        }

        let stream = res.bytes_stream().eventsource().map(|event| match event {
            Ok(ev) => {
                if let Ok(json_res) = serde_json::from_str::<serde_json::Value>(&ev.data) {
                    let text = json_res["candidates"][0]["content"]["parts"][0]["text"]
                        .as_str()
                        .unwrap_or("")
                        .to_string();
                    let finish_reason = json_res["candidates"][0].get("finishReason");
                    let is_finished = finish_reason.is_some() && finish_reason != Some(&serde_json::Value::Null);

                    let usage = json_res.get("usageMetadata").map(|u| TokenUsage {
                        prompt_tokens: u["promptTokenCount"].as_u64().unwrap_or(0) as u32,
                        completion_tokens: u["candidatesTokenCount"].as_u64().unwrap_or(0) as u32,
                        total_tokens: u["totalTokenCount"].as_u64().unwrap_or(0) as u32,
                    });

                    Ok(GenerateStreamChunk {
                        text,
                        is_finished: Some(is_finished),
                        usage,
                        metadata: Some(json_res),
                    })
                } else {
                    Err(ProviderError::ApiError(
                        "Failed to parse VertexAI stream JSON".to_string(),
                    ))
                }
            }
            Err(e) => Err(ProviderError::ApiError(e.to_string())),
        });

        Ok(Box::pin(stream))
    }
}
