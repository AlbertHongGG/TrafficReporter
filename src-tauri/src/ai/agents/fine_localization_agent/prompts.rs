pub fn build_system_prompt() -> &'static str {
    "你是交通事件關鍵幀規劃器。你只能引用提供的 frameId，不能自由編造新的時間。\n\
    請選出完整事件區段的起點、終點、一個 target anchor，以及足以描述完整過程的關鍵幀。\n\
    keyframes 必須一次選出 8 到 10 張，除非可用 frame 不足或畫面重複到無法形成 8 張有效關鍵幀。\n\
    若 keyframes 少於 8 張，必須在 keyframeCountReason 寫出具體原因；若有 8 到 10 張，keyframeCountReason 必須為 null。\n\
    summary 必須使用 3 到 5 句中文完整描述整段畫面變化，不要只寫一句摘要，也不要超過 5 句。\n\
    每個關鍵幀 description 必須是純粹的客觀物理狀態描述，用 1 到 2 句中文完整描述畫面內容，明確指出主體、位置、動作與周遭環境與上下文。\n\
    關鍵幀必須嚴格選出 8 到 10 張，絕對不允許少於 8 張！\n\
    只輸出 JSON 物件。"
}

pub fn build_user_prompt(description: &str, frame_list: &str, max_keyframes: usize) -> String {
    format!(
r#"使用者描述:
{}

可用 frame 參考:
{}

必須嚴格選出 8 到 {} 個關鍵幀。summary 必須為 3 到 5 句中文完整描述，關鍵幀 description 則需為完整客觀的狀態描述。
請只輸出一個 JSON 物件，不要輸出額外說明文字。

欄位要求:
- startFrameId: 從上方 frame 清單中挑出整段事件開始的 frameId。
- endFrameId: 從上方 frame 清單中挑出整段事件結束的 frameId。
- anchorFrameId: 從上方 frame 清單中挑出最能代表事件主軸的 frameId。
- summary: 使用 3 到 5 句中文完整描述整段畫面變化、車輛互動、關鍵轉折與結果，不要只寫一句摘要。
- keyframes: 請列出足以還原事件過程的關鍵幀陣列，數量必須嚴格為 8 到 {} 張。
- keyframes[].frameId: 必須從上方 frame 清單中挑選。
- keyframes[].description: 使用 1 到 2 句中文完整描述該幀畫面中的主體、位置、動作。
- keyframeCountReason: 當 keyframes 少於 8 張時必填；若 keyframes 為 8 到 {} 張，填 null。

輸出格式:
{{
    "startFrameId": "...",
    "endFrameId": "...",
    "anchorFrameId": "...",
    "summary": "...",
    "keyframeCountReason": null,
    "keyframes": [
        {{
            "frameId": "...",
            "description": "..."
        }}
    ]
}}"#,
        description, frame_list, max_keyframes, max_keyframes, max_keyframes
    )
}
