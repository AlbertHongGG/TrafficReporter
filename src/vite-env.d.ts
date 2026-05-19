/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_LPR_TARGET_OVERLAY_TOLERANCE_MS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}