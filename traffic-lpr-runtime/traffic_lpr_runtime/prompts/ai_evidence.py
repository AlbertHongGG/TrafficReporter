from __future__ import annotations

from textwrap import dedent


def _prompt(text: str) -> str:
    return dedent(text).strip()


COARSE_SYSTEM_PROMPT = _prompt(
    """
    你是交通事件關鍵證據規劃器。你只能引用系統提供的 frameId，不能自行猜測時間。
    請根據使用者描述，從提供的 frameId 中找出最可能涵蓋完整事件過程的起點、終點與 anchor。
    只輸出 JSON 物件。
    """
)

COARSE_USER_PROMPT_TEMPLATE = _prompt(
    """
    使用者描述:
    $description

    可用 frame 參考:
    $frameList

    請只輸出一個 JSON 物件，不要輸出額外說明文字。

    欄位要求:
    - startFrameId: 從上方 frame 清單中挑出「事件開始」的 frameId。
    - endFrameId: 從上方 frame 清單中挑出「事件結束」的 frameId。
    - anchorFrameId: 從上方 frame 清單中挑出最適合代表整段事件核心畫面的 frameId。
    - summary: 用 1 到 2 句中文說明你為什麼選這段區間，內容要聚焦在事件過程本身。

    輸出格式:
    {
        "startFrameId": "...",
        "endFrameId": "...",
        "anchorFrameId": "...",
        "summary": "..."
    }
    """
)

FINE_SYSTEM_PROMPT = _prompt(
    """
    你是交通事件關鍵幀規劃器。你只能引用提供的 frameId，不能自由編造新的時間。
    請選出完整事件區段的起點、終點、一個 target anchor，以及足以描述完整過程的關鍵幀。
    summary 必須使用 3 到 5 句中文完整描述整段畫面變化，不要只寫一句摘要，也不要超過 5 句。
    每個關鍵幀 description 必須使用 1 到 2 句中文完整描述畫面中的主體、位置、動作與上下文，不要只寫短標籤或片語。
    只輸出 JSON 物件。
    """
)

FINE_USER_PROMPT_TEMPLATE = _prompt(
    """
    使用者描述:
    $description

    可用 frame 參考:
    $frameList

    最多可選 $maxKeyframes 個關鍵幀。summary 必須為 3 到 5 句中文完整描述，關鍵幀 description 則需為完整描述句。

    請只輸出一個 JSON 物件，不要輸出額外說明文字。

    欄位要求:
    - startFrameId: 從上方 frame 清單中挑出整段事件開始的 frameId。
    - endFrameId: 從上方 frame 清單中挑出整段事件結束的 frameId。
    - anchorFrameId: 從上方 frame 清單中挑出最能代表事件主軸的 frameId。
    - summary: 使用 3 到 5 句中文完整描述整段畫面變化、車輛互動、關鍵轉折與結果，不要只寫一句摘要。
    - keyframes: 請列出足以還原事件過程的關鍵幀陣列。
    - keyframes[].frameId: 必須從上方 frame 清單中挑選。
    - keyframes[].description: 使用 1 到 2 句中文完整描述該幀畫面中的主體、位置、動作、與它在事件中的意義。

    輸出格式:
    {
        "startFrameId": "...",
        "endFrameId": "...",
        "anchorFrameId": "...",
        "summary": "...",
        "keyframes": [
            {
                "frameId": "...",
                "description": "..."
            }
        ]
    }
    """
)

TARGET_SYSTEM_PROMPT = _prompt(
    """
    你是交通事件 target resolver。你必須只從提供的候選 target IDs 中選出最符合描述的目標。
    請結合 anchor overview、各個 target crop、以及結構化 OCR 證據判斷。
    只輸出 JSON。
    """
)

TARGET_USER_PROMPT_TEMPLATE = _prompt(
    """
    請根據以下 JSON 證據與對應圖片選擇 target。targets[*].imageFrameId 會對應到提供的 crop 圖。
    如果 exactPlateHintMatches 非空，代表 OCR 與描述中的車牌提示完全一致，這是 strong prior；只有當畫面證據明確矛盾時，才可改選其他 target，並將 plateHintConsistency 設為 contradicted。

    $promptPayload

    請只輸出一個 JSON 物件，不要輸出額外說明文字。

    欄位要求:
    - selectedTrackId: 你最終選定的 target track id，必須來自候選 target。
    - selectedCandidateId: 對應的 OCR candidate id；如果該 target 沒有可用 candidate，則填 null。
    - confidence: 0.0 到 1.0 的信心分數。
    - plateHintConsistency: 僅能填 supporting、neutral、contradicted、not-applicable 其中之一。
    - rationale: 使用中文完整說明你選這個 target 的理由，必須引用畫面證據、OCR 證據或兩者的關係。

    輸出格式:
    {
        "selectedTrackId": "...",
        "selectedCandidateId": "...",
        "confidence": 0.0,
        "plateHintConsistency": "supporting|neutral|contradicted|not-applicable",
        "rationale": "..."
    }
    """
)