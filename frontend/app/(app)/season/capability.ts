import { CAPABILITY_LABELS, REQUIRES_TO_CAPABILITY } from './types'
import type { CapabilitiesFlags, RequiresFlags } from './types'

export interface CapabilityCheck {
  ok: boolean
  missing: string[]
}

/** Checks whether a driver's capabilities cover a ride/loop's required-flags profile. */
export function checkCapabilityCoverage(
  requires: RequiresFlags | null | undefined,
  capabilities: CapabilitiesFlags | null | undefined
): CapabilityCheck {
  const missing: string[] = []
  if (!requires) return { ok: true, missing }

  for (const [flag, capKey] of Object.entries(REQUIRES_TO_CAPABILITY) as [keyof RequiresFlags, keyof CapabilitiesFlags][]) {
    if (requires[flag] && !capabilities?.[capKey]) {
      missing.push(CAPABILITY_LABELS[capKey])
    }
  }

  return { ok: missing.length === 0, missing }
}

/** Merges the requires-profiles of every ride in a loop into one combined profile. */
export function mergeRequiresProfiles(rides: { requires: RequiresFlags }[]): RequiresFlags {
  const merged: RequiresFlags = {}
  for (const ride of rides) {
    for (const key of Object.keys(ride.requires || {}) as (keyof RequiresFlags)[]) {
      if (ride.requires[key]) merged[key] = true
    }
  }
  return merged
}
