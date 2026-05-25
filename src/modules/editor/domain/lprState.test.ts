import { describe, expect, it } from 'vitest'

import { buildDefaultLprState } from './lprState'

describe('lprState', () => {
  it('enables developer diagnostics by default', () => {
    expect(buildDefaultLprState().showDeveloperDiagnostics).toBe(true)
  })

  it('preserves an explicit developer diagnostics override', () => {
    expect(buildDefaultLprState({ showDeveloperDiagnostics: false }).showDeveloperDiagnostics).toBe(false)
  })
})