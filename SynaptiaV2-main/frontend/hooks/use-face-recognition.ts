"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import * as faceapi from "face-api.js"

export interface FaceIdentity {
  name: string
  relationship?: string
  description?: string
  descriptor: number[]
}

export interface FaceMatch {
  name: string
  relationship?: string
  description?: string
  distance: number
}

export interface EnrollmentOptions {
  name: string
  relationship?: string
  description?: string
  targetBox?: { originX: number; originY: number; width: number; height: number }
  targetFaceId?: string
}

export interface EnrollmentResult {
  success: boolean
  error?: string
  name?: string
  relationship?: string
}

const MODEL_URL = "/models/face-api"
const MATCH_THRESHOLD = 0.52
const LOCAL_STORAGE_KEY = "synaptia_v2_face_identities"
const MISS_THRESHOLD = 4

function getLocalIdentities(): FaceIdentity[] {
  if (typeof window === "undefined") return []
  try {
    const raw = localStorage.getItem(LOCAL_STORAGE_KEY)
    return raw ? (JSON.parse(raw) as FaceIdentity[]) : []
  } catch {
    return []
  }
}

function saveLocalIdentities(identities: FaceIdentity[]) {
  if (typeof window === "undefined") return
  try {
    localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(identities))
  } catch (err) {
    console.warn("[FaceRecognition] Failed to save to localStorage:", err)
  }
}

function computeBoxOverlap(
  mBox: { originX: number; originY: number; width: number; height: number },
  fBox: { x: number; y: number; width: number; height: number }
): number {
  const x1 = Math.max(mBox.originX, fBox.x)
  const y1 = Math.max(mBox.originY, fBox.y)
  const x2 = Math.min(mBox.originX + mBox.width, fBox.x + fBox.width)
  const y2 = Math.min(mBox.originY + mBox.height, fBox.y + fBox.height)

  const interW = Math.max(0, x2 - x1)
  const interH = Math.max(0, y2 - y1)
  const interArea = interW * interH
  if (interArea <= 0) return 0

  const mArea = mBox.width * mBox.height
  const fArea = fBox.width * fBox.height
  const unionArea = mArea + fArea - interArea
  return unionArea > 0 ? interArea / unionArea : 0
}

function computeCenterDistance(
  mBox: { originX: number; originY: number; width: number; height: number },
  fBox: { x: number; y: number; width: number; height: number }
): number {
  const mCenterX = mBox.originX + mBox.width / 2
  const mCenterY = mBox.originY + mBox.height / 2
  const fCenterX = fBox.x + fBox.width / 2
  const fCenterY = fBox.y + fBox.height / 2
  return Math.hypot(mCenterX - fCenterX, mCenterY - fCenterY)
}

export function useFaceRecognition(
  video: HTMLVideoElement | null,
  enabled: boolean,
  trackedFaces: Array<{ id: string; boundingBox: { originX: number; originY: number; width: number; height: number } }> = []
) {
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Per-face recognition matches (faceId -> FaceMatch)
  const [matches, setMatches] = useState<Record<string, FaceMatch>>({})
  // Active primary match for backward compatibility
  const [match, setMatch] = useState<FaceMatch | null>(null)

  const [enrolledIdentities, setEnrolledIdentities] = useState<FaceIdentity[]>(getLocalIdentities())
  const identitiesRef = useRef<FaceIdentity[]>(getLocalIdentities())
  const recognitionInFlightRef = useRef(false)
  const missCountByFaceIdRef = useRef<Map<string, number>>(new Map())
  const cachedMatchesRef = useRef<Map<string, FaceMatch>>(new Map())
  const trackedFacesRef = useRef(trackedFaces)
  trackedFacesRef.current = trackedFaces

  const loadIdentities = useCallback(async () => {
    // 1. Load immediately from local storage
    const local = getLocalIdentities()
    if (local.length > 0) {
      identitiesRef.current = local
      setEnrolledIdentities(local)
    }

    // 2. Fetch from backend and merge
    try {
      const response = await fetch("http://localhost:8002/api/face-identities")
      if (response.ok) {
        const body = (await response.json()) as { identities?: FaceIdentity[] }
        const serverIdentities = body.identities ?? []

        // Merge by name without case-sensitive duplicates
        const map = new Map<string, FaceIdentity>()
        for (const id of local) map.set(id.name.toLowerCase(), id)
        for (const id of serverIdentities) {
          const key = id.name.toLowerCase()
          const existing = map.get(key)
          map.set(key, {
            ...existing,
            ...id,
            relationship: id.relationship || existing?.relationship,
            description: id.description || existing?.description,
          })
        }

        const merged = Array.from(map.values())
        identitiesRef.current = merged
        saveLocalIdentities(merged)
        setEnrolledIdentities(merged)
      }
    } catch (err) {
      console.warn("[FaceRecognition] Could not sync identities with server, using local copy:", err)
    }
  }, [])

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      try {
        setIsLoading(true)
        await Promise.all([
          faceapi.nets.tinyFaceDetector.loadFromUri(MODEL_URL),
          faceapi.nets.faceLandmark68Net.loadFromUri(MODEL_URL),
          faceapi.nets.faceRecognitionNet.loadFromUri(MODEL_URL),
          loadIdentities(),
        ])
        if (!cancelled) {
          setError(null)
          setIsLoading(false)
        }
      } catch (cause) {
        const message = cause instanceof Error ? cause.message : "Unable to load face recognition"
        console.error("[FaceRecognition] Initialization error:", cause)
        if (!cancelled) {
          setError(message)
          setIsLoading(false)
        }
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [loadIdentities])

  const detectAllDescriptors = useCallback(async () => {
    if (!video || video.videoWidth === 0 || video.videoHeight === 0) {
      return []
    }

    try {
      return await faceapi
        .detectAllFaces(video, new faceapi.TinyFaceDetectorOptions({ inputSize: 224, scoreThreshold: 0.35 }))
        .withFaceLandmarks()
        .withFaceDescriptors()
    } catch (err) {
      console.warn("[FaceRecognition] Multi-face detection failed:", err)
      return []
    }
  }, [video])

  // Recognition loop: detects all faces in frame and maps them to tracked individuals
  useEffect(() => {
    if (!enabled || isLoading || !video) {
      return
    }

    const interval = window.setInterval(() => {
      if (recognitionInFlightRef.current) {
        return
      }
      recognitionInFlightRef.current = true

      void (async () => {
        try {
          const detections = await detectAllDescriptors()
          const currentTracked = trackedFacesRef.current
          const currentTrackedIds = new Set(currentTracked.map((f) => f.id))

          // Clean up lost faces from temporal cache
          for (const faceId of cachedMatchesRef.current.keys()) {
            if (!currentTrackedIds.has(faceId)) {
              cachedMatchesRef.current.delete(faceId)
              missCountByFaceIdRef.current.delete(faceId)
            }
          }

          if (detections.length === 0) {
            // No faces detected by faceapi this frame: increment miss count for all
            for (const face of currentTracked) {
              const misses = (missCountByFaceIdRef.current.get(face.id) ?? 0) + 1
              missCountByFaceIdRef.current.set(face.id, misses)
              if (misses >= MISS_THRESHOLD) {
                cachedMatchesRef.current.delete(face.id)
              }
            }

            const updatedMatches = Object.fromEntries(cachedMatchesRef.current.entries())
            setMatches(updatedMatches)
            const primaryMatch = Object.values(updatedMatches)[0] ?? null
            setMatch(primaryMatch)
            return
          }

          // Spatial association: Match faceapi detections to MediaPipe tracked faces
          const faceDescriptors: Array<{ faceId: string; descriptor: Float32Array; box: faceapi.Box }> = []
          const usedDetections = new Set<number>()

          for (const tracked of currentTracked) {
            let bestIndex = -1
            let bestScore = -1

            for (let i = 0; i < detections.length; i++) {
              if (usedDetections.has(i)) continue
              const fBox = detections[i].detection.box
              const iou = computeBoxOverlap(tracked.boundingBox, fBox)
              const maxDim = Math.max(tracked.boundingBox.width, tracked.boundingBox.height)
              const dist = computeCenterDistance(tracked.boundingBox, fBox)

              // Prefer strong IoU or close center distance
              const score = iou > 0.15 ? iou + 1 : dist < maxDim * 0.8 ? 1 - dist / (maxDim * 0.8) : -1
              if (score > bestScore) {
                bestScore = score
                bestIndex = i
              }
            }

            if (bestIndex >= 0 && bestScore > 0) {
              usedDetections.add(bestIndex)
              faceDescriptors.push({
                faceId: tracked.id,
                descriptor: detections[bestIndex].descriptor,
                box: detections[bestIndex].detection.box,
              })
            }
          }

          // Fallback if tracked faces don't align or trackedFaces is empty: use detection index as faceId
          if (faceDescriptors.length === 0 && detections.length > 0) {
            detections.forEach((d, idx) => {
              faceDescriptors.push({
                faceId: `detected_${idx}`,
                descriptor: d.descriptor,
                box: d.detection.box,
              })
            })
          }

          // Match extracted descriptors against enrolled identities (with greedy 1-to-1 matching)
          const identities = identitiesRef.current
          const candidateMatches: Array<{ faceId: string; identity: FaceIdentity; distance: number }> = []

          for (const item of faceDescriptors) {
            for (const id of identities) {
              if (!id.descriptor || id.descriptor.length !== item.descriptor.length) continue
              const distance = faceapi.euclideanDistance(item.descriptor, new Float32Array(id.descriptor))
              if (distance <= MATCH_THRESHOLD) {
                candidateMatches.push({ faceId: item.faceId, identity: id, distance })
              }
            }
          }

          // Sort by lowest distance (highest confidence)
          candidateMatches.sort((a, b) => a.distance - b.distance)

          const assignedFaces = new Set<string>()
          const assignedNames = new Set<string>()
          const frameMatches = new Map<string, FaceMatch>()

          // Assign each identity uniquely to at most one face per frame
          for (const c of candidateMatches) {
            const nameKey = c.identity.name.toLowerCase()
            if (!assignedFaces.has(c.faceId) && !assignedNames.has(nameKey)) {
              assignedFaces.add(c.faceId)
              assignedNames.add(nameKey)
              frameMatches.set(c.faceId, {
                name: c.identity.name,
                relationship: c.identity.relationship,
                description: c.identity.description,
                distance: c.distance,
              })
            }
          }

          // Update cache with smoothing for each tracked face
          for (const tracked of currentTracked) {
            const newMatch = frameMatches.get(tracked.id)
            if (newMatch) {
              missCountByFaceIdRef.current.set(tracked.id, 0)
              cachedMatchesRef.current.set(tracked.id, newMatch)
            } else {
              const misses = (missCountByFaceIdRef.current.get(tracked.id) ?? 0) + 1
              missCountByFaceIdRef.current.set(tracked.id, misses)
              if (misses >= MISS_THRESHOLD) {
                cachedMatchesRef.current.delete(tracked.id)
              }
            }
          }

          // Also retain any fallback unassociated detected faces
          for (const [fId, fMatch] of frameMatches.entries()) {
            if (fId.startsWith("detected_")) {
              cachedMatchesRef.current.set(fId, fMatch)
            }
          }

          const updatedMatches = Object.fromEntries(cachedMatchesRef.current.entries())
          setMatches(updatedMatches)

          // Set primary match (lowest distance among recognized faces)
          const sortedMatches = Object.values(updatedMatches).sort((a, b) => a.distance - b.distance)
          setMatch(sortedMatches[0] ?? null)
        } catch (cause) {
          console.error("[FaceRecognition] Matching error:", cause)
        } finally {
          recognitionInFlightRef.current = false
        }
      })()
    }, 1000)

    return () => window.clearInterval(interval)
  }, [detectAllDescriptors, enabled, isLoading, video])

  // Multi-individual enrollment supporting targeted face selection and relationship
  const enroll = useCallback(
    async (
      nameOrOptions: string | EnrollmentOptions,
      optionalRelationship?: string
    ): Promise<EnrollmentResult> => {
      let name = ""
      let relationship: string | undefined = optionalRelationship
      let description: string | undefined
      let targetBox: { originX: number; originY: number; width: number; height: number } | undefined

      if (typeof nameOrOptions === "string") {
        name = nameOrOptions.trim()
      } else {
        name = nameOrOptions.name.trim()
        relationship = nameOrOptions.relationship?.trim() || relationship
        description = nameOrOptions.description?.trim()
        targetBox = nameOrOptions.targetBox
      }

      if (!name) {
        return { success: false, error: "Enter a name before enrolling." }
      }

      try {
        const detections = await detectAllDescriptors()
        if (detections.length === 0) {
          return { success: false, error: "Keep a face clearly in view of the camera, then try again." }
        }

        // Find the specific target detection if targetBox provided
        let targetDetection = detections[0]
        if (targetBox && detections.length > 1) {
          let bestOverlap = -1
          let bestDist = Infinity

          for (const d of detections) {
            const overlap = computeBoxOverlap(targetBox, d.detection.box)
            const dist = computeCenterDistance(targetBox, d.detection.box)
            if (overlap > bestOverlap || (overlap === bestOverlap && dist < bestDist)) {
              bestOverlap = overlap
              bestDist = dist
              targetDetection = d
            }
          }
        } else if (detections.length > 1) {
          // If multiple faces and no targetBox specified, pick the largest detection
          targetDetection = detections.reduce((largest, d) => {
            const area = d.detection.box.width * d.detection.box.height
            const largestArea = largest.detection.box.width * largest.detection.box.height
            return area > largestArea ? d : largest
          }, detections[0])
        }

        const newIdentity: FaceIdentity = {
          name,
          relationship: relationship || undefined,
          description: description || undefined,
          descriptor: Array.from(targetDetection.descriptor),
        }

        // Update local storage
        const currentLocal = getLocalIdentities().filter(
          (id) => id.name.toLowerCase() !== name.toLowerCase()
        )
        currentLocal.push(newIdentity)
        saveLocalIdentities(currentLocal)
        identitiesRef.current = currentLocal
        setEnrolledIdentities(currentLocal)

        // Sync to backend
        try {
          await fetch("http://localhost:8002/api/face-identities", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(newIdentity),
          })
        } catch (err) {
          console.warn("[FaceRecognition] Could not sync enrolled identity to backend:", err)
        }

        // Immediately update matches for instant responsiveness
        const newMatch: FaceMatch = {
          name,
          relationship: newIdentity.relationship,
          description: newIdentity.description,
          distance: 0,
        }
        setMatch(newMatch)

        return { success: true, name, relationship: newIdentity.relationship }
      } catch (cause) {
        const message = cause instanceof Error ? cause.message : "Face enrollment failed"
        console.error("[FaceRecognition] Enrollment error:", cause)
        return { success: false, error: message }
      }
    },
    [detectAllDescriptors]
  )

  return { isLoading, error, matches, match, enroll, loadIdentities, identities: enrolledIdentities }
}
