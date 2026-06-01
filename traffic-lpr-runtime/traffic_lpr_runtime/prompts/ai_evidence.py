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
    keyframes 必須一次選出 8 到 10 張，除非可用 frame 不足或畫面重複到無法形成 8 張有效關鍵幀。
    若 keyframes 少於 8 張，必須在 keyframeCountReason 寫出具體原因；若有 8 到 10 張，keyframeCountReason 必須為 null。
    summary 必須使用 3 到 5 句中文完整描述整段畫面變化，不要只寫一句摘要，也不要超過 5 句。
    每個關鍵幀 description 必須是純粹的客觀物理狀態描述，用 1 到 2 句中文完整描述畫面內容，明確指出主體、位置、動作與周遭環境與上下文。絕對不可以只寫短標籤或片語，或是包含「這是事件進行中的關鍵畫面」、「請重點查看...」這類多餘的指引或評論性廢話，需要的是描述狀態的陳述，而不是無意義的廢物。
    關鍵幀必須嚴格選出 8 到 10 張，絕對不允許少於 8 張！即便畫面變化不大，也必須在時間軸上均勻選取以湊齊至少 8 張有效關鍵幀。
    如果事件包含明顯動作轉折，例如轉彎、變換車道、超車、煞停、進出路口，至少要包含「動作開始前」、「動作進行中（例如：正在轉彎、車身已明顯偏轉）」、「動作接近完成或完成」的畫面；絕對不能只選動作前和動作後而遺漏進行中的畫面。
    每個 description 只能描述該 frame 當下看得到的內容，不可以把前後幀的資訊、推測中的後續動作、或整段事件摘要塞進單一畫面描述。
    只輸出 JSON 物件。
    """
)

FINE_USER_PROMPT_TEMPLATE = _prompt(
    """
    使用者描述:
    $description

    可用 frame 參考:
    $frameList

    必須嚴格選出 8 到 $maxKeyframes 個關鍵幀。summary 必須為 3 到 5 句中文完整描述，關鍵幀 description 則需為完整客觀的狀態描述。
    沒有 retry 的機會請在這一次輸出中一次到位。
    關鍵幀集合必須呈現時間上的完整過程，而不是平均抽樣或尾段連拍。若是右轉、左轉、迴轉、變換車道、超車、切入、煞停等事件，必須清楚涵蓋「動作前」、「動作開始」、「動作進行中（例如：正在轉彎、車身偏轉）」、「動作完成或接近完成」這幾種不同階段。遺漏任一狀態的畫面都是嚴重的疏失。
    每個 description 都必須只對應該幀當下可見的事實：主體在哪裡、朝向如何、正在做什麼、與路口/護欄/其他車輛的相對位置是什麼。請直接客觀地描述狀態，嚴禁加上「這是關鍵畫面」、「請重點查看」等任何引導性廢話。不要描述該幀看不到的「即將」或「已經」發生之事。

    請只輸出一個 JSON 物件，不要輸出額外說明文字。

    欄位要求:
    - startFrameId: 從上方 frame 清單中挑出整段事件開始的 frameId。
    - endFrameId: 從上方 frame 清單中挑出整段事件結束的 frameId。
    - anchorFrameId: 從上方 frame 清單中挑出最能代表事件主軸的 frameId。
    - summary: 使用 3 到 5 句中文完整描述整段畫面變化、車輛互動、關鍵轉折與結果，不要只寫一句摘要。
    - keyframes: 請列出足以還原事件過程的關鍵幀陣列，數量必須嚴格為 8 到 $maxKeyframes 張，絕對不能少於 8 張。
    - keyframes[].frameId: 必須從上方 frame 清單中挑選。
    - keyframes[].description: 使用 1 到 2 句中文完整描述該幀畫面中的主體、位置、動作、與它在事件中的意義，但只能寫該幀當下看得到的資訊。
    - keyframeCountReason: 當 keyframes 少於 8 張時必填，說明可用 frame 不足、重複畫面太多、或缺少可判讀畫面等具體原因；若 keyframes 為 8 到 $maxKeyframes 張，填 null。

    輸出格式:
    {
        "startFrameId": "...",
        "endFrameId": "...",
        "anchorFrameId": "...",
        "summary": "...",
        "keyframeCountReason": null,
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