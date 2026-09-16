"use client"

const INFERENCE_BACKEND_URL = "http://localhost:8002"

/**
 * Extracts a zero-mean centered, formant-weighted 128-dimensional acoustic spectral
 * voice descriptor from Web Audio Analyser frequency data.
 *
 * Centering around the vector mean removes background room hum and constant microphone DC bias,
 * creating distinct positive/negative formant peaks unique to individual speakers.
 */
export function extractVoiceDescriptor(frequencyData: Float32Array): number[] {
  const descriptorLength = 128
  const step = Math.max(1, Math.floor(frequencyData.length / descriptorLength))
  const raw: number[] = new Array(descriptorLength).fill(0)

  for (let i = 0; i < descriptorLength; i++) {
    const idx = Math.min(i * step, frequencyData.length - 1)
    const db = frequencyData[idx]
    // Normalized amplitude [0, 1]
    const amp = Math.max(0, (db + 100) / 100)
    // Weight fundamental frequency and speech formants (bins ~100Hz - 3.5kHz)
    const speechWeight = i >= 2 && i <= 64 ? 1.4 : 0.8
    raw[i] = amp * speechWeight
  }

  // Zero-mean centering (spectral Pearson correlation alignment)
  const mean = raw.reduce((sum, val) => sum + val, 0) / descriptorLength
  const centered = raw.map((val) => val - mean)
  const norm = Math.sqrt(centered.reduce((sum, val) => sum + val * val, 0))

  if (norm === 0) return new Array(descriptorLength).fill(0)
  return centered.map((val) => Number((val / norm).toFixed(5)))
}

/**
 * Computes zero-mean normalized correlation (Pearson spectral correlation)
 * between two acoustic voice descriptor vectors.
 */
export function computeVoiceSimilarity(vecA: number[], vecB: number[]): number {
  if (!vecA || !vecB || vecA.length === 0 || vecB.length === 0) return 0
  const len = Math.min(vecA.length, vecB.length)

  const aSlice = vecA.slice(0, len)
  const bSlice = vecB.slice(0, len)

  const meanA = aSlice.reduce((s, v) => s + v, 0) / len
  const meanB = bSlice.reduce((s, v) => s + v, 0) / len

  const centA = aSlice.map((v) => v - meanA)
  const centB = bSlice.map((v) => v - meanB)

  let dot = 0
  let normA = 0
  let normB = 0
  for (let i = 0; i < len; i++) {
    dot += centA[i] * centB[i]
    normA += centA[i] * centA[i]
    normB += centB[i] * centB[i]
  }

  const denom = Math.sqrt(normA) * Math.sqrt(normB)
  return denom === 0 ? 0 : Math.max(-1, Math.min(1, dot / denom))
}

/**
 * Saves the enrolled acoustic voice descriptor for a named user.
 */
export async function enrollVoiceprint(personName: string, descriptor: number[]): Promise<boolean> {
  const cleanName = personName.trim()
  if (!cleanName || descriptor.length === 0) return false

  // Store in browser localStorage for offline capability
  try {
    localStorage.setItem(`synaptia_voice_${cleanName.toLowerCase()}`, JSON.stringify(descriptor))
  } catch {}

  // Persist to inference service backend
  try {
    const res = await fetch(`${INFERENCE_BACKEND_URL}/api/voice-identities`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: cleanName,
        descriptor,
      }),
    })
    return res.ok
  } catch (err) {
    console.warn("[VoiceDescriptor] Backend voice enrollment failed (cached locally):", err)
    return true
  }
}

/**
 * Loads the enrolled voice descriptor for a person from backend or local storage.
 */
export async function getEnrolledVoiceprint(personName: string): Promise<number[] | null> {
  const cleanName = personName.trim().toLowerCase()
  if (!cleanName) return null

  // 1. Check localStorage first
  try {
    const local = localStorage.getItem(`synaptia_voice_${cleanName}`)
    if (local) {
      const parsed = JSON.parse(local)
      if (Array.isArray(parsed) && parsed.length > 0) return parsed
    }
  } catch {}

  // 2. Fetch from backend
  try {
    const res = await fetch(`${INFERENCE_BACKEND_URL}/api/voice-identities/${encodeURIComponent(cleanName)}`)
    if (res.ok) {
      const data = await res.json()
      if (data.descriptor && Array.isArray(data.descriptor)) {
        try {
          localStorage.setItem(`synaptia_voice_${cleanName}`, JSON.stringify(data.descriptor))
        } catch {}
        return data.descriptor
      }
    }
  } catch {}

  return null
}

/**
 * Deletes enrolled voiceprint for a person from backend and local storage.
 */
export async function deleteEnrolledVoiceprint(personName: string): Promise<boolean> {
  const cleanName = personName.trim()
  if (!cleanName) return false

  try {
    localStorage.removeItem(`synaptia_voice_${cleanName.toLowerCase()}`)
  } catch {}

  try {
    const res = await fetch(`${INFERENCE_BACKEND_URL}/api/voice-identities/${encodeURIComponent(cleanName)}`, {
      method: "DELETE",
    })
    return res.ok
  } catch {
    return true
  }
}

/**
 * Fetches all enrolled voice identities from the backend.
 */
export async function fetchEnrolledVoiceList(): Promise<string[]> {
  try {
    const res = await fetch(`${INFERENCE_BACKEND_URL}/api/voice-identities`)
    if (res.ok) {
      const data = await res.json()
      return (data.identities || []).map((id: { name: string }) => id.name)
    }
  } catch {}
  return []
}

export interface DistinctConversationEntry {
  id: string
  person_name: string
  speaker: string
  text: string
  summary?: string
  voice_verified: boolean
  timestamp: string
}

/**
 * Retrieves distinct conversations for a specific individual.
 */
export async function fetchPersonConversations(personName: string): Promise<DistinctConversationEntry[]> {
  const cleanName = personName.trim()
  if (!cleanName) return []

  try {
    const res = await fetch(`${INFERENCE_BACKEND_URL}/api/conversations/${encodeURIComponent(cleanName)}`)
    if (res.ok) {
      const data = await res.json()
      return data.conversations || []
    }
  } catch (err) {
    console.error(`Failed to fetch conversations for ${cleanName}:`, err)
  }
  return []
}

/**
 * Clears conversation history for a specific individual.
 */
export async function clearPersonConversations(personName: string): Promise<boolean> {
  const cleanName = personName.trim()
  if (!cleanName) return false

  try {
    const res = await fetch(`${INFERENCE_BACKEND_URL}/api/conversations/${encodeURIComponent(cleanName)}`, {
      method: "DELETE",
    })
    return res.ok
  } catch (err) {
    console.error(`Failed to clear conversations for ${cleanName}:`, err)
    return false
  }
}
