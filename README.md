# Traffic Reporter

桌面應用：匯入行車紀錄影片，掃描並追蹤車牌、OCR 辨識、AI 證據分析，在時間軸上剪輯後匯出證據片段。

## 功能

- **車牌掃描**：YOLO 偵測＋多目標追蹤，鎖定目標車輛
- **辨識融合**：OCR 多幀融合＋可靠度篩選，輸出最佳車牌候選
- **AI 證據分析**：關鍵影格故事板＋視覺語言模型複核（本機 Ollama 或雲端）
- **時間軸剪輯**：播放、標記、裁剪、匯出片段／關鍵影格
- **多視窗**：主工作區、車牌、AI 證據、匯出四視窗同步

## 系統需求

- Windows 10/11（目前僅支援 Windows）
- Node.js 22+、Rust stable、Python 3.12+
- 本機 AI 分析需 [Ollama](https://ollama.com)（預設模型見 `.env.example`）
- `src-tauri/bin/` 需自行放入 `ffmpeg.exe`、`ffprobe.exe`（授權因素未隨 repo 發布）

## 快速開始

```bash
npm install
cp .env.example .env        # 依需求修改，見「設定」
npm run tauri dev           # 啟動桌面應用（開發模式）
```

打包：

```bash
npm run build:installer     # 安裝程式
npm run build:portable      # 免安裝綠色版（dist-portable/）
```

## 設定

`.env`（不進版控，以 `.env.example` 為範本）：

| 變數 | 說明 | 預設 |
|---|---|---|
| `TRAFFIC_AI_PROVIDER` | `ollama`（本機）、`geminiflow`、`vertexai` | `ollama` |
| `TRAFFIC_OLLAMA_URL` / `TRAFFIC_OLLAMA_MODEL` | Ollama 位址與模型 | 見範本 |
| `TRAFFIC_AI_EVIDENCE_MAX_KEYFRAMES` | AI 分析關鍵影格上限 | `8` |
| `VITE_LPR_TARGET_OVERLAY_TOLERANCE_MS` | 目標框顯示容忍毫秒 | `360` |

## 測試

```bash
npm test                                   # 前端（vitest）
python -m unittest discover -s traffic-lpr-runtime/tests -p "test_*.py"   # Python runtime
cargo test --manifest-path src-tauri/Cargo.toml                            # Rust
```

## 專案結構

```
src/                        React 前端（Zustand 狀態、use-case 服務、typed IPC 邊界）
src-tauri/src/              Rust 後端（commands / application 服務 / contracts / media / events）
traffic-lpr-runtime/        Python LPR 引擎（前處理 / 追蹤 / 融合 / 分析 / use cases）
```

型別契約由 Rust 經 Specta 生成（`src/domain/ipc/bindings.ts`），請勿手改——改 Rust 側後跑 `npm run bindings:generate`。
