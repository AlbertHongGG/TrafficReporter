import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores([
    'dist',
    'dist-portable',
    'src-tauri/target',
    'src-tauri/gen',
    'traffic-lpr-runtime/**',
    'src/types/bindings.ts',
    'src/domain/ipc/bindings.ts',
  ]),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
  },
  // ---------------------------------------------------------------------------
  // Phase 1-C anti-regression guardrails (TrafficRebuildBlueprint §7 + §1.1).
  // Intent: lock the "single source of truth" skeleton so the rebuild cannot
  // silently rot back into 3-type drift / `as any` / God files.
  // All rules below use ESLint built-ins only (no new plugins).
  // Full enforcement lands in Phase 7; file-length stays `warn` until then.
  // ---------------------------------------------------------------------------
  {
    // Rule 1 (blueprint §7 / §2.2): only `infrastructure/*` may touch
    // `bindings.commands`. Per-module `infrastructure/*Api.ts` is the sole
    // layer allowed to import it; workflow hooks / reducers / domain must go
    // through the infra API + mapper instead.
    // NOTE: `importNames: ['commands']` keeps `import type { ... }` from
    // bindings legal everywhere (domain files SHOULD reference bindings types).
    files: ['src/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: [
                '**/types/bindings',
                '@/types/bindings',
                '**/domain/ipc/bindings',
                '@/domain/ipc/bindings',
              ],
              importNames: ['commands'],
              message:
                'Only files under src/**/infrastructure/ may import `commands` from bindings (blueprint §2.2). Call the per-module infrastructure/*Api instead.',
            },
          ],
        },
      ],
      // Rule 2 (blueprint §1.2): ban `as any` in src/. Cross-process payloads
      // are validated once at the infrastructure boundary (§2.3); domain code
      // receives already-clean objects. (`: any` annotations remain covered by
      // @typescript-eslint/no-explicit-any from the recommended set.)
      'no-restricted-syntax': [
        'error',
        {
          selector: "TSAsExpression[typeAnnotation.type='TSAnyKeyword']",
          message:
            'Ban `as any` in src/ (blueprint §1.2). Route cross-process payloads through the infrastructure boundary validator instead.',
        },
        {
          selector: "TSTypeAssertion[typeAnnotation.type='TSAnyKeyword']",
          message:
            'Ban `<any>` assertions in src/ (blueprint §1.2). Route cross-process payloads through the infrastructure boundary validator instead.',
        },
      ],
      // Rule 4 (blueprint §7): file-length guard, ~250 lines per file in src/.
      // Phase 1: `warn` only (not blocking); escalate to `error` in Phase 7
      // when the God-file split (§3–§6) is complete.
      'max-lines': [
        'warn',
        {
          max: 250,
          skipBlankLines: true,
          skipComments: false,
        },
      ],
    },
  },
  {
    // Rule 1 exemption: the infrastructure layer itself. Later flat-config
    // blocks override same-rule entries, so this narrowly lifts only
    // `no-restricted-imports` for infra files; other rules above still apply.
    files: ['src/**/infrastructure/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': 'off',
    },
  },
  {
    // Rule 3 (blueprint §1.1): domain files must NOT redeclare type names
    // owned by bindings — they must `import type` them from bindings instead.
    // NOTE: flat-config merges per-rule (later array replaces earlier), so the
    // `as any` selectors from the src-wide block are repeated here to keep
    // both bans active inside domain files.
    files: ['src/**/domain/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: "TSAsExpression[typeAnnotation.type='TSAnyKeyword']",
          message:
            'Ban `as any` in src/ (blueprint §1.2). Route cross-process payloads through the infrastructure boundary validator instead.',
        },
        {
          selector: "TSTypeAssertion[typeAnnotation.type='TSAnyKeyword']",
          message:
            'Ban `<any>` assertions in src/ (blueprint §1.2). Route cross-process payloads through the infrastructure boundary validator instead.',
        },
        {
          selector:
            'TSInterfaceDeclaration[id.name=/^(VideoMarkerRect|TimelineClip|TimelineTrack|TimelineIntervalSelection|EditorAsset|RenderProfile|ExportSnapshot)$/]',
          message:
            'Do not redeclare bindings-owned types in domain files (blueprint §1.1). `import type { ... }` from bindings instead.',
        },
        {
          // Type aliases with these names are only banned when they declare a
          // fresh shape (no type reference inside). Aliases derived from
          // bindings (e.g. NonNullable-mapped lift-types over *Payload) are
          // the approved migration pattern (blueprint §1.1) and are allowed.
          selector:
            'TSTypeAliasDeclaration[id.name=/^(VideoMarkerRect|TimelineClip|TimelineTrack|TimelineIntervalSelection|EditorAsset|RenderProfile|ExportSnapshot)$/]:not(:has(TSTypeReference))',
          message:
            'Do not redeclare bindings-owned types in domain files (blueprint §1.1). `import type { ... }` from bindings instead.',
        },
      ],
    },
  },
])
