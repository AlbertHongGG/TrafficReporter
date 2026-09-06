pub mod coarse_localization_agent;
pub mod fine_localization_agent;
pub mod target_resolution_agent;

use async_trait::async_trait;
use serde_json::Value;
use std::sync::Arc;

use crate::ai::providers::{AIProvider, ProviderError};

#[derive(Debug, thiserror::Error)]
pub enum AgentError {
    #[error("Provider Error: {0}")]
    Provider(#[from] ProviderError),
    #[error("Invalid Input: {0}")]
    InvalidInput(String),
    #[error("Invalid Output: {0}")]
    InvalidOutput(String),
    #[error("Execution Error: {0}")]
    Execution(String),
}

#[async_trait]
pub trait Agent: Send + Sync {
    fn name(&self) -> &'static str;
    async fn execute(&self, input: Value) -> Result<Value, AgentError>;
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum AgentType {
    CoarseLocalization,
    FineLocalization,
    TargetResolution,
}

pub struct AgentFactory;

impl AgentFactory {
    pub fn create_agent(
        agent_type: AgentType,
        provider: Arc<dyn AIProvider>,
        model: String,
    ) -> Box<dyn Agent> {
        match agent_type {
            AgentType::CoarseLocalization => Box::new(
                coarse_localization_agent::CoarseLocalizationAgent::new(provider, model),
            ),
            AgentType::FineLocalization => Box::new(
                fine_localization_agent::FineLocalizationAgent::new(provider, model),
            ),
            AgentType::TargetResolution => Box::new(
                target_resolution_agent::TargetResolutionAgent::new(provider, model),
            ),
        }
    }
}
