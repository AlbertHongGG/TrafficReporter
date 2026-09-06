use eventsource_stream::Eventsource;
use futures_util::stream::{BoxStream, StreamExt};
use reqwest::Client;
use serde_json::Value;

use super::types::{GeminiFlowChatPayload, GeminiFlowChatResponse, GeminiFlowStreamData};
use crate::ai::providers::ProviderError;

pub struct GeminiFlowClient {
    base_url: String,
    client: Client,
}

impl GeminiFlowClient {
    pub fn new(base_url: String) -> Self {
        Self {
            base_url: base_url.trim_end_matches('/').to_string(),
            client: Client::new(),
        }
    }

    pub async fn chat(
        &self,
        payload: GeminiFlowChatPayload,
    ) -> Result<(GeminiFlowChatResponse, Value), ProviderError> {
        let endpoint = format!("{}/chat", self.base_url);

        let res = self.client.post(&endpoint).json(&payload).send().await?;

        if !res.status().is_success() {
            let status = res.status();
            let err_text = res.text().await.unwrap_or_default();
            return Err(ProviderError::ApiError(format!(
                "{} - {}",
                status, err_text
            )));
        }

        let json_res: Value = res.json().await?;
        let response: GeminiFlowChatResponse = serde_json::from_value(json_res.clone())?;

        Ok((response, json_res))
    }

    pub async fn stream(
        &self,
        payload: GeminiFlowChatPayload,
    ) -> Result<
        BoxStream<'static, Result<(Option<GeminiFlowStreamData>, Value, bool), ProviderError>>,
        ProviderError,
    > {
        let endpoint = format!("{}/stream", self.base_url);

        let res = self.client.post(&endpoint).json(&payload).send().await?;

        if !res.status().is_success() {
            let status = res.status();
            let err_text = res.text().await.unwrap_or_default();
            return Err(ProviderError::ApiError(format!(
                "{} - {}",
                status, err_text
            )));
        }

        let stream = res.bytes_stream().eventsource().map(|event| match event {
            Ok(ev) => {
                if ev.data == "[DONE]" || ev.event == "done" {
                    return Ok((None, Value::Null, true));
                }
                if let Ok(json_res) = serde_json::from_str::<Value>(&ev.data) {
                    if let Ok(stream_data) =
                        serde_json::from_value::<GeminiFlowStreamData>(json_res.clone())
                    {
                        Ok((Some(stream_data), json_res, false))
                    } else {
                        Ok((None, json_res, false))
                    }
                } else {
                    Err(ProviderError::ApiError(
                        "Failed to parse stream JSON".to_string(),
                    ))
                }
            }
            Err(e) => Err(ProviderError::ApiError(e.to_string())),
        });

        Ok(Box::pin(stream))
    }
}
