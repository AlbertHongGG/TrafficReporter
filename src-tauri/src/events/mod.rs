use serde::Serialize;
use tauri::Emitter;

use crate::contracts::{
    AiEvidenceProgressKind, AiEvidenceProgressPayload, LprAnalysisProvenancePayload,
    LprProgressPayload, LprReviewStatePayload, LprTrackingTier,
};

const APP_LOG_EVENT: &str = "app/log";
const LPR_PROGRESS_EVENT: &str = "editor/lpr-progress";
const AI_EVIDENCE_PROGRESS_EVENT: &str = "editor/ai-evidence-progress";
pub const AI_EVIDENCE_WORKFLOW_STEP_COUNT: u32 = 11;

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct AppLogPayload {
    level: String,
    scope: String,
    message: String,
}

pub fn emit_app_log(app_handle: &tauri::AppHandle, level: &str, scope: &str, message: impl Into<String>) {
    let message = message.into();
    match level {
        "debug" => log::debug!(target: scope, "{}", message),
        "info" => log::info!(target: scope, "{}", message),
        "warn" => log::warn!(target: scope, "{}", message),
        _ => log::error!(target: scope, "{}", message),
    }

    let _ = app_handle.emit(
        APP_LOG_EVENT,
        AppLogPayload {
            level: level.to_string(),
            scope: scope.to_string(),
            message,
        },
    );
}

pub fn emit_lpr_request_log(
    app_handle: &tauri::AppHandle,
    command: &str,
    request_id: Option<&str>,
    analysis_profile_id: Option<&str>,
    developer_diagnostics_enabled: bool,
) {
    emit_app_log(
        app_handle,
        "info",
        "LprRuntimeRequest",
        format!(
            "command={} requestId={} profile={} developerDiagnostics={}",
            command,
            request_id.unwrap_or("-"),
            analysis_profile_id.unwrap_or("-"),
            developer_diagnostics_enabled,
        ),
    );
}

pub fn emit_lpr_result_log(
    app_handle: &tauri::AppHandle,
    provenance: &LprAnalysisProvenancePayload,
    review: &LprReviewStatePayload,
    candidate_count: usize,
) {
    emit_app_log(
        app_handle,
        "info",
        "LprRuntimeResult",
        format!(
            "command={} requestId={} status={} suggested={} accepted={} candidates={} profile={} runtimeVersion={}",
            provenance.command,
            provenance.request_id.as_deref().unwrap_or("-"),
            review.status,
            review.suggested_candidate_id.as_deref().unwrap_or("-"),
            review.accepted_candidate_id.as_deref().unwrap_or("-"),
            candidate_count,
            provenance.analysis_profile_id.as_deref().unwrap_or("-"),
            provenance.runtime_version.as_deref().unwrap_or("-"),
        ),
    );
}

pub fn emit_ai_evidence_progress(
    app_handle: &tauri::AppHandle,
    request_id: Option<&str>,
    progress: f64,
    stage: &str,
    detail: impl Into<String>,
    done: bool,
    failed: bool,
    progress_kind: Option<AiEvidenceProgressKind>,
    tool_name: Option<&str>,
    tool_label: Option<&str>,
    step_index: Option<u32>,
    step_count: Option<u32>,
    stage_step_index: Option<u32>,
    stage_step_count: Option<u32>,
) {
    let _ = app_handle.emit(
        AI_EVIDENCE_PROGRESS_EVENT,
        AiEvidenceProgressPayload {
            progress,
            stage: stage.to_string(),
            detail: detail.into(),
            progress_kind,
            tool_name: tool_name.map(|value| value.to_string()),
            tool_label: tool_label.map(|value| value.to_string()),
            step_index,
            step_count,
            stage_step_index,
            stage_step_count,
            done,
            failed,
            request_id: request_id.map(|value| value.to_string()),
        },
    );
}

pub fn emit_ai_evidence_progress_payload(
    app_handle: &tauri::AppHandle,
    progress: AiEvidenceProgressPayload,
) {
    emit_ai_evidence_progress(
        app_handle,
        progress.request_id.as_deref(),
        progress.progress,
        &progress.stage,
        progress.detail,
        progress.done,
        progress.failed,
        progress.progress_kind,
        progress.tool_name.as_deref(),
        progress.tool_label.as_deref(),
        progress.step_index,
        progress.step_count,
        progress.stage_step_index,
        progress.stage_step_count,
    );
}

pub fn emit_lpr_progress(
    app_handle: &tauri::AppHandle,
    request_id: Option<&str>,
    progress: f64,
    stage: &str,
    detail: impl Into<String>,
    done: bool,
    failed: bool,
    reason_code: Option<&str>,
    tracking_tier: Option<LprTrackingTier>,
    coverage_ratio: Option<f64>,
) {
    let _ = app_handle.emit(
        LPR_PROGRESS_EVENT,
        LprProgressPayload {
            progress,
            stage: stage.to_string(),
            detail: detail.into(),
            done,
            failed,
            request_id: request_id.map(|value| value.to_string()),
            reason_code: reason_code.map(|value| value.to_string()),
            tracking_tier,
            coverage_ratio,
        },
    );
}
