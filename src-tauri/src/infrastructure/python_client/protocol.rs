use std::time::Duration;

use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::contracts::LprRuntimeStatusPayload;

pub(crate) const LPR_RUNTIME_PROTOCOL_VERSION: u8 = 1;
pub(crate) const DEFAULT_LPR_RUNTIME_REQUEST_TIMEOUT: Duration = Duration::from_secs(300);

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct RuntimeWorkerRequest<'a, TRequest: Serialize> {
    pub(crate) protocol_version: u8,
    pub(crate) request_id: u64,
    pub(crate) subcommand: &'a str,
    pub(crate) payload: &'a TRequest,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct RuntimeWorkerResponse<TResponse> {
    protocol_version: u8,
    request_id: u64,
    kind: Option<String>,
    ok: Option<bool>,
    progress: Option<Value>,
    result: Option<TResponse>,
    error: Option<String>,
    runtime: Option<LprRuntimeStatusPayload>,
    traceback: Option<String>,
}

#[derive(Debug)]
pub(crate) enum RuntimeWorkerInvokeError {
    Recoverable(String),
    Unrecoverable(String),
}

pub(crate) enum RuntimeWorkerEnvelope<TResponse> {
    Progress(Value),
    Success(TResponse),
    Error(RuntimeWorkerResponse<TResponse>),
}

pub(crate) fn deserialize_progress_payload<TProgress>(
    progress: Value,
) -> Result<TProgress, RuntimeWorkerInvokeError>
where
    TProgress: DeserializeOwned,
{
    serde_json::from_value(progress).map_err(|error| {
        RuntimeWorkerInvokeError::Recoverable(format!(
            "Failed to parse the LPR runtime worker progress payload: {}",
            error,
        ))
    })
}

pub(crate) fn request_timeout_for_subcommand(_subcommand: &str) -> Duration {
    DEFAULT_LPR_RUNTIME_REQUEST_TIMEOUT
}

pub(crate) fn cancel_generation_changed(invoke_generation: u64, current_generation: u64) -> bool {
    invoke_generation != current_generation
}

pub(crate) fn parse_worker_response_line<TResponse>(
    response_line: &str,
    request_id: u64,
    protocol_version: u8,
) -> Result<RuntimeWorkerEnvelope<TResponse>, RuntimeWorkerInvokeError>
where
    TResponse: DeserializeOwned,
{
    let response: RuntimeWorkerResponse<TResponse> = serde_json::from_str(response_line.trim_end()).map_err(|error| {
        RuntimeWorkerInvokeError::Unrecoverable(format!(
            "Failed to parse the LPR runtime worker response: {}\n{}",
            error,
            response_line.trim()
        ))
    })?;

    if response.request_id != request_id {
        return Err(RuntimeWorkerInvokeError::Recoverable(format!(
            "Mismatched LPR runtime worker response: expected request {}, received {}.",
            request_id,
            response.request_id,
        )));
    }

    if response.protocol_version != protocol_version {
        return Err(RuntimeWorkerInvokeError::Unrecoverable(format!(
            "Mismatched LPR runtime worker protocol: expected version {}, received {}.",
            protocol_version,
            response.protocol_version,
        )));
    }

    if response.kind.as_deref() == Some("progress") {
        let progress = response.progress.ok_or_else(|| {
            RuntimeWorkerInvokeError::Recoverable(
                "The local LPR runtime worker emitted a progress envelope without a progress payload.".to_string(),
            )
        })?;
        return Ok(RuntimeWorkerEnvelope::Progress(progress));
    }

    if response.ok == Some(true) {
        let result = response.result.ok_or_else(|| {
            RuntimeWorkerInvokeError::Unrecoverable(
                "The local LPR runtime worker returned success without a payload.".to_string(),
            )
        })?;
        return Ok(RuntimeWorkerEnvelope::Success(result));
    }

    Ok(RuntimeWorkerEnvelope::Error(response))
}

pub(crate) fn format_worker_error<TResponse>(response: RuntimeWorkerResponse<TResponse>) -> String {
    let mut detail = response
        .error
        .unwrap_or_else(|| "The local LPR runtime worker reported an error.".to_string());

    if let Some(runtime) = response.runtime {
        let runtime_detail = runtime.detail.trim();
        if !runtime_detail.is_empty() && runtime_detail != detail {
            detail = format!("{}\n{}", detail, runtime_detail);
        }
    }

    if let Some(traceback) = response.traceback {
        let traceback = traceback.trim();
        if !traceback.is_empty() {
            detail = format!("{}\n{}", detail, traceback);
        }
    }

    detail
}

#[cfg(test)]
mod tests {
    use crate::contracts::AiEvidenceProgressPayload;
    use serde_json::Value;

    use super::{
        cancel_generation_changed, deserialize_progress_payload, parse_worker_response_line,
        request_timeout_for_subcommand, RuntimeWorkerEnvelope, RuntimeWorkerInvokeError,
        DEFAULT_LPR_RUNTIME_REQUEST_TIMEOUT,
    };

    #[test]
    fn cancel_generation_change_marks_active_request_cancelled() {
        assert!(!cancel_generation_changed(7, 7));
        assert!(cancel_generation_changed(7, 8));
    }

    #[test]
    fn parse_worker_response_line_accepts_progress_envelopes() {
        let envelope = parse_worker_response_line::<Value>(
            r#"{"protocolVersion":1,"requestId":7,"kind":"progress","progress":{"requestId":"req-7","progress":0.4,"stage":"Interval","detail":"Analyzing tracked sample 2/5.","done":false,"failed":false,"reasonCode":null,"trackingTier":"partial","coverageRatio":0.4}}"#,
            7,
            1,
        )
        .expect("progress envelope should parse");

        match envelope {
            RuntimeWorkerEnvelope::Progress(progress) => {
                assert_eq!(progress.get("requestId").and_then(Value::as_str), Some("req-7"));
                assert_eq!(progress.get("stage").and_then(Value::as_str), Some("Interval"));
                assert_eq!(progress.get("detail").and_then(Value::as_str), Some("Analyzing tracked sample 2/5."));
                assert_eq!(progress.get("trackingTier").and_then(Value::as_str), Some("partial"));
                assert_eq!(progress.get("coverageRatio").and_then(Value::as_f64), Some(0.4));
            }
            RuntimeWorkerEnvelope::Success(_) | RuntimeWorkerEnvelope::Error(_) => {
                panic!("expected a progress envelope")
            }
        }
    }

    #[test]
    fn deserialize_progress_payload_ignores_unknown_fields_for_ai_progress() {
        let progress = deserialize_progress_payload::<AiEvidenceProgressPayload>(serde_json::json!({
            "requestId": "req-11",
            "progress": 0.6,
            "stage": "range-analysis",
            "detail": "Analyzing tracked sample 2/5.",
            "done": false,
            "failed": false,
            "trackingTier": "partial",
            "coverageRatio": 0.4
        }))
        .expect("ai progress payload should deserialize");

        assert_eq!(progress.request_id.as_deref(), Some("req-11"));
        assert_eq!(progress.stage, "range-analysis");
        assert_eq!(progress.detail, "Analyzing tracked sample 2/5.");
        assert!((progress.progress - 0.6).abs() < f64::EPSILON);
    }

    #[test]
    fn parse_worker_response_line_accepts_success_envelopes() {
        let envelope = parse_worker_response_line::<Value>(
            r#"{"protocolVersion":1,"requestId":8,"ok":true,"result":{"status":"ok","samples":3}}"#,
            8,
            1,
        )
        .expect("success envelope should parse");

        match envelope {
            RuntimeWorkerEnvelope::Success(result) => {
                assert_eq!(result.get("status").and_then(Value::as_str), Some("ok"));
                assert_eq!(result.get("samples").and_then(Value::as_i64), Some(3));
            }
            RuntimeWorkerEnvelope::Progress(_) | RuntimeWorkerEnvelope::Error(_) => {
                panic!("expected a success envelope")
            }
        }
    }

    #[test]
    fn parse_worker_response_line_rejects_progress_without_payload() {
        let result = parse_worker_response_line::<Value>(
            r#"{"protocolVersion":1,"requestId":9,"kind":"progress"}"#,
            9,
            1,
        );

        match result {
            Err(RuntimeWorkerInvokeError::Recoverable(message)) => {
                assert!(message.contains("without a progress payload"));
            }
            Ok(_) | Err(RuntimeWorkerInvokeError::Unrecoverable(_)) => {
                panic!("expected a recoverable progress payload error")
            }
        }
    }

    #[test]
    fn request_timeout_for_subcommand_uses_default_timeout() {
        let timeout = request_timeout_for_subcommand("analyze-interval");
        assert_eq!(timeout, DEFAULT_LPR_RUNTIME_REQUEST_TIMEOUT);
    }

    #[test]
    fn parse_worker_response_line_deserializes_frame_analysis_with_all_reasons() {
        let json_line = serde_json::json!({
            "protocolVersion": 1,
            "requestId": 10,
            "ok": true,
            "result": {
                "detections": [],
                "sample": {
                    "id": "sample-100",
                    "timeMs": 100.0,
                    "targetBox": null,
                    "plateBox": null,
                    "quality": null,
                    "candidates": [],
                    "imagePath": null,
                    "selection": {
                        "selected": true,
                        "priority": 1.0,
                        "reasons": ["anchor", "sharpness-peak", "interval-start", "temporal-burst"]
                    },
                    "ocrInput": {
                        "stage": "original",
                        "variant": "original",
                        "source": "single-frame",
                        "imagePath": null,
                        "supportFrameCount": 1
                    },
                    "temporalSupport": null,
                    "diagnostics": null
                },
                "candidates": [],
                "acceptedCandidateId": null,
                "review": {
                    "status": "accepted",
                    "suggestedCandidateId": null,
                    "acceptedCandidateId": null,
                    "reviewRequired": false,
                    "confidence": 0.9,
                    "margin": 0.2,
                    "reasons": []
                },
                "provenance": {
                    "requestId": "req-1",
                    "command": "analyze-frame",
                    "analysisProfileId": "precision",
                    "developerDiagnosticsEnabled": false,
                    "runtimeVersion": "3.12.10",
                    "restorationMode": "off",
                    "recognizerBackend": "hybrid",
                    "temporalEvidenceMode": "motion-aware",
                    "sequenceReviewMode": "strict",
                    "emittedAtMs": 1000.0
                },
                "decision": {
                    "source": "single-frame",
                    "candidateId": null,
                    "sampleId": "sample-100",
                    "frameTimeMs": 100.0,
                    "stage": "original",
                    "supportFrameCount": 1,
                    "agreementRatio": null,
                    "margin": null
                },
                "runtime": {
                    "available": true,
                    "pythonExecutable": "python.exe",
                    "runtimeScript": "main.py",
                    "version": "3.12.10",
                    "missingPackages": [],
                    "installedPackages": ["torch"],
                    "detail": "ok"
                },
                "jobStatus": "completed",
                "diagnostics": null
            }
        }).to_string();

        let envelope = parse_worker_response_line::<crate::contracts::lpr::LprFrameAnalysisResponsePayload>(
            &json_line,
            10,
            1,
        ).expect("should successfully parse frame analysis response with anchor and reasons");

        match envelope {
            RuntimeWorkerEnvelope::Success(payload) => {
                let sample = payload.sample.expect("sample should be present");
                let selection = sample.selection.expect("selection should be present");
                assert_eq!(selection.reasons.len(), 4);
                assert_eq!(selection.reasons[0], crate::contracts::lpr::LprEvidenceReason::Anchor);
                assert_eq!(selection.reasons[1], crate::contracts::lpr::LprEvidenceReason::SharpnessPeak);
            }
            _ => panic!("expected success envelope"),
        }
    }
}
