pub fn build_system_prompt() -> &'static str {
    "你是交通事件關鍵證據規劃器。你只能引用系統提供的 frameId，不能自行猜測時間。\n\
    請根據使用者描述，從提供的 frameId 中找出最可能涵蓋完整事件過程的起點、終點與 anchor。\n\
    只輸出 JSON 物件。"
}

pub fn build_user_prompt(description: &str, frame_list: &str) -> String {
    format!(
r#"使用者描述:
{}

可用 frame 參考:
{}

請只輸出一個 JSON 物件，不要輸出額外說明文字。

欄位要求:
- startFrameId: 從上方 frame 清單中挑出「事件開始」的 frameId。
- endFrameId: 從上方 frame 清單中挑出「事件結束」的 frameId。
- anchorFrameId: 從上方 frame 清單中挑出最適合代表整段事件核心畫面的 frameId。
- summary: 用 1 到 2 句中文說明你為什麼選這段區間，內容要聚焦在事件過程本身。

輸出格式:
{{
    "startFrameId": "...",
    "endFrameId": "...",
    "anchorFrameId": "...",
    "summary": "..."
}}"#,
        description, frame_list
    )
}
