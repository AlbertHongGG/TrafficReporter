pub fn build_system_prompt() -> &'static str {
    "你是交通事件 target resolver。你必須只從提供的候選 target IDs 中選出最符合描述的目標。\n\
    請結合 anchor overview、各個 target crop、以及結構化 OCR 證據判斷。\n\
    只輸出 JSON。"
}

pub fn build_user_prompt(prompt_payload_json: &str) -> String {
    format!(
r#"請根據以下 JSON 證據與對應圖片選擇 target。targets[*].imageFrameId 會對應到提供的 crop 圖。
如果 exactPlateHintMatches 非空，代表 OCR 與描述中的車牌提示完全一致，這是 strong prior；只有當畫面證據明確矛盾時，才可改選其他 target，並將 plateHintConsistency 設為 contradicted。

{}

請只輸出一個 JSON 物件，不要輸出額外說明文字。

欄位要求:
- selectedTrackId: 你最終選定的 target track id，必須來自候選 target。
- selectedCandidateId: 對應的 OCR candidate id；如果該 target 沒有可用 candidate，則填 null。
- confidence: 0.0 到 1.0 的信心分數。
- plateHintConsistency: 僅能填 supporting、neutral、contradicted、not-applicable 其中之一。
- rationale: 使用中文完整說明你選這個 target 的理由，必須引用畫面證據、OCR 證據或兩者的關係。

輸出格式:
{{
    "selectedTrackId": "...",
    "selectedCandidateId": "...",
    "confidence": 0.0,
    "plateHintConsistency": "supporting|neutral|contradicted|not-applicable",
    "rationale": "..."
}}"#,
        prompt_payload_json
    )
}
