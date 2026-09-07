// Hub: workflow engine entry point + submodule re-exports.
// Caller paths (e.g. `crate::ai::workflow::AiEvidenceWorkflowEngine`) are unchanged.
mod steps_coarse;
mod steps_finalize;
mod steps_fine;
mod steps_target;
mod types;

pub use types::{StoryboardFrameItem, StoryboardFramesResponse};

use std::fs;
use std::sync::Arc;

use tauri::AppHandle;

use crate::ai::providers::{AIProvider, ProviderFactory};
use crate::contracts::{
    AiEvidenceProgressKind, AiEvidenceRequestPayload, AiEvidenceResponsePayload,
    AiEvidenceToolCallPayload,
};
use crate::editor::{
    emit_ai_evidence_progress, runtime_run_root, AI_EVIDENCE_WORKFLOW_STEP_COUNT,
};

use types::now_ms;

pub struct AiEvidenceWorkflowEngine {
    pub(crate) app_handle: AppHandle,
    pub(crate) provider: Arc<dyn AIProvider>,
    pub(crate) model: String,
}

impl AiEvidenceWorkflowEngine {
    pub fn new(app_handle: AppHandle, provider: Arc<dyn AIProvider>, model: String) -> Self {
        Self {
            app_handle,
            provider,
            model,
        }
    }

    pub fn resolve_default_provider() -> Result<(Arc<dyn AIProvider>, String), String> {
        let provider_name = std::env::var("TRAFFIC_AI_PROVIDER")
            .unwrap_or_else(|_| "ollama".to_string())
            .to_lowercase();
        let model = std::env::var("TRAFFIC_AI_MODEL")
            .unwrap_or_else(|_| match provider_name.as_str() {
                "geminiflow" => "gemini-2.5-flash".to_string(),
                "vertexai" => "gemini-2.5-flash".to_string(),
                _ => "qwen2.5-vl".to_string(),
            });
        let base_url = std::env::var("TRAFFIC_AI_BASE_URL").ok();
        let provider = ProviderFactory::create_provider(&provider_name, &model, base_url.as_deref())
            .map_err(|e| format!("Failed to create AI provider: {}", e))?;
        Ok((provider, model))
    }

    pub async fn run(
        &self,
        request: AiEvidenceRequestPayload,
    ) -> Result<AiEvidenceResponsePayload, String> {
        let request_id = request
            .request_id
            .clone()
            .unwrap_or_else(|| format!("ai-evidence-{}", now_ms()));

        let run_dir = runtime_run_root(&request_id)?.join("ai-evidence");
        let coarse_dir = run_dir.join("coarse");
        let fine_dir = run_dir.join("fine");
        let keyframes_dir = run_dir.join("keyframes");

        fs::create_dir_all(&run_dir).map_err(|e| e.to_string())?;
        fs::create_dir_all(&coarse_dir).map_err(|e| e.to_string())?;
        fs::create_dir_all(&fine_dir).map_err(|e| e.to_string())?;
        fs::create_dir_all(&keyframes_dir).map_err(|e| e.to_string())?;

        let mut tool_calls: Vec<AiEvidenceToolCallPayload> = Vec::new();

        // 1. Prepare
        emit_ai_evidence_progress(
            &self.app_handle,
            Some(&request_id),
            0.05,
            "prepare",
            "Preparing AI evidence workflow.",
            false,
            false,
            Some(AiEvidenceProgressKind::HostStep),
            None,
            None,
            Some(1),
            Some(AI_EVIDENCE_WORKFLOW_STEP_COUNT),
            Some(1),
            Some(1),
        );

        // 2-3. Coarse storyboard sampling + AI coarse localization
        let t_coarse_start = now_ms() as f64;
        let coarse_storyboard = self
            .sample_coarse_storyboard(&request, &request_id, &coarse_dir)
            .await?;
        let (coarse_start_ms, coarse_end_ms, coarse_summary) = self
            .localize_coarse_interval(&request, &request_id, &coarse_storyboard, t_coarse_start, &mut tool_calls)
            .await?;

        // 4-5. Fine storyboard sampling + AI fine localization & keyframe selection
        let t_fine_start = now_ms() as f64;
        let (fine_storyboard, fine_start, fine_end) = self
            .sample_fine_storyboard(&request, &request_id, &coarse_storyboard, coarse_start_ms, coarse_end_ms, &fine_dir)
            .await?;
        let (anchor_frame_item, anchor_time_ms, fine_summary, fine_output) = self
            .localize_fine_keyframes(&request, &request_id, &fine_storyboard, t_fine_start, &mut tool_calls)
            .await?;

        // 6-7. Scan targets on anchor frame + target resolution
        let t_target_start = now_ms() as f64;
        let scan_res = self
            .scan_anchor_targets(&request, &request_id, anchor_time_ms)
            .await?;
        let (selected_box, selected_track_id) = self
            .resolve_target_selection(&request, &request_id, &scan_res, anchor_time_ms, t_target_start, &mut tool_calls)
            .await?;

        // 8. Range analysis (analyze-interval)
        let (interval_res, final_start_ms, final_end_ms) = self
            .analyze_target_interval(&request, &request_id, fine_start, fine_end, anchor_time_ms, &selected_box, &selected_track_id)
            .await?;

        // 9. Export evidence clip
        let clip_path = self
            .export_evidence_clip(&request, &request_id, &run_dir, final_start_ms, final_end_ms)?;

        // 10. Assemble response payload
        let response = self.assemble_evidence_response(
            request,
            request_id.clone(),
            coarse_summary,
            fine_summary,
            &fine_output,
            &fine_storyboard,
            anchor_frame_item,
            selected_box,
            selected_track_id,
            interval_res,
            clip_path,
            final_start_ms,
            final_end_ms,
            tool_calls,
        )?;

        emit_ai_evidence_progress(
            &self.app_handle,
            Some(&request_id),
            1.0,
            "completed",
            "AI evidence workflow completed.",
            true,
            false,
            Some(AiEvidenceProgressKind::HostStep),
            None,
            None,
            Some(11),
            Some(AI_EVIDENCE_WORKFLOW_STEP_COUNT),
            Some(1),
            Some(1),
        );

        Ok(response)
    }
}
