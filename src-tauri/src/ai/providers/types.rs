use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ChatMessage {
    pub role: String,
    pub content: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct GenerateRequest {
    pub prompt: String,
    pub system_prompt: Option<String>,
    pub messages: Option<Vec<ChatMessage>>,
    pub temperature: Option<f32>,
    pub max_tokens: Option<u32>,
    pub images: Option<Vec<String>>,
    pub session_id: Option<String>,
    pub stream: Option<bool>,
}

#[derive(Debug, Serialize, Deserialize, Clone, Default)]
pub struct TokenUsage {
    pub prompt_tokens: u32,
    pub completion_tokens: u32,
    pub total_tokens: u32,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct GenerateResponse {
    pub text: String,
    pub usage: Option<TokenUsage>,
    pub metadata: Option<Value>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct GenerateStreamChunk {
    pub text: String,
    pub is_finished: Option<bool>,
    pub usage: Option<TokenUsage>,
    pub metadata: Option<Value>,
}
