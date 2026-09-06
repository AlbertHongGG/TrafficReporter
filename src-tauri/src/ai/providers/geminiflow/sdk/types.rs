use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Clone)]
pub struct GeminiFlowChatPayload {
    pub prompt: String,
    pub model: String,
    pub language: String,
    pub save_images: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub system_prompt: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub images: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub session_id: Option<String>,
}

#[derive(Debug, Deserialize, Clone)]
pub struct GeminiFlowChatResponse {
    pub text: String,
    pub images: Option<Vec<String>>,
}

#[derive(Debug, Deserialize, Clone)]
pub struct GeminiFlowStreamData {
    #[serde(alias = "chunk")]
    pub text: String,
    pub images: Option<Vec<String>>,
}
