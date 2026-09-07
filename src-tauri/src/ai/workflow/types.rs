use std::fs;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use base64::Engine;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StoryboardFrameItem {
    pub frame_id: String,
    pub time_ms: i64,
    pub sequence_index: usize,
    pub label: String,
    pub image_path: String,
    pub frame_width: u32,
    pub frame_height: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StoryboardFramesResponse {
    pub source_path: String,
    pub duration_ms: i64,
    pub output_dir: String,
    pub frames: Vec<StoryboardFrameItem>,
}

pub(crate) fn load_and_encode_images(frames: &[StoryboardFrameItem]) -> Result<Vec<String>, String> {
    let mut images = Vec::with_capacity(frames.len());
    for f in frames {
        let path = Path::new(&f.image_path);
        let bytes = fs::read(path).map_err(|e| format!("Failed to read image at {:?}: {}", path, e))?;
        let base64_str = base64::engine::general_purpose::STANDARD.encode(&bytes);
        images.push(base64_str);
    }
    Ok(images)
}

pub(crate) fn now_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|v| v.as_millis())
        .unwrap_or(0)
}
