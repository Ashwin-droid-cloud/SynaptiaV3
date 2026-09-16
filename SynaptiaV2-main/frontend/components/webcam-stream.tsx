"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { Mic, MicOff, Video, VideoOff, Users, CheckCircle2, AlertCircle, MessageSquare, Volume2, X, RefreshCw } from "lucide-react"
import { FaceNotification } from "@/components/face-notification"
import { useFaceDetection } from "@/hooks/use-face-detection"
import { useFaceRecognition, type FaceMatch } from "@/hooks/use-face-recognition"
import { useServerTranscription, deduplicateSummary } from "@/hooks/use-server-transcription"
import {
  fetchEnrolledVoiceList,
  deleteEnrolledVoiceprint,
  fetchPersonConversations,
  clearPersonConversations,
  type DistinctConversationEntry,
} from "@/lib/voice-descriptor"
import type { DetectedFace } from "@/lib/face-tracker"
import { RayBanOverlay } from "@/components/rayban-overlay"
import { cn } from "@/lib/utils"
import {
  calculateVideoTransform,
  mapBoundingBoxToOverlay,
  calculateNotificationPosition,
} from "@/lib/coordinate-mapper"

// Track when faces were first seen (for unidentified timeout)
type FaceTimestampMap = Map<string, number>

const UNIDENTIFIED_TIMEOUT_MS = 4000 // Show "Unidentified" after 4 seconds with no match
const INFERENCE_BACKEND_URL = "http://localhost:8002"

function captureFaceCrop(video: HTMLVideoElement, face: DetectedFace): string | null {
  const { originX, originY, width, height } = face.boundingBox
  const sourceX = Math.max(0, Math.floor(originX))
  const sourceY = Math.max(0, Math.floor(originY))
  const sourceWidth = Math.min(Math.ceil(width), video.videoWidth - sourceX)
  const sourceHeight = Math.min(Math.ceil(height), video.videoHeight - sourceY)

  if (sourceWidth <= 0 || sourceHeight <= 0) {
    return null
  }

  const canvas = document.createElement("canvas")
  const targetWidth = Math.min(192, sourceWidth)
  canvas.width = targetWidth
  canvas.height = Math.max(1, Math.round((sourceHeight / sourceWidth) * targetWidth))
  const context = canvas.getContext("2d")
  if (!context) {
    return null
  }

  context.drawImage(
    video,
    sourceX,
    sourceY,
    sourceWidth,
    sourceHeight,
    0,
    0,
    canvas.width,
    canvas.height
  )
  return canvas.toDataURL("image/jpeg", 0.8)
}

export default function WebcamStream() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const overlayRef = useRef<HTMLDivElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [isVideoReady, setIsVideoReady] = useState(false)
  const [cameraError, setCameraError] = useState<string | null>(null)
  const [isSimulatedStream, setIsSimulatedStream] = useState(false)
  const [simPreset, setSimPreset] = useState("sarah_jenkins")
  const simulationIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const simulationCanvasRef = useRef<HTMLCanvasElement | null>(null)
  const [unidentifiedFaceIds, setUnidentifiedFaceIds] = useState<Set<string>>(new Set())
  const [isRayBanMode, setIsRayBanMode] = useState(false)
  const [isMuted, setIsMuted] = useState(false)
  const [faceStorageError, setFaceStorageError] = useState<string | null>(null)

  // Enrollment fields supporting multi-individual identification & relationship tags
  const [enrollmentName, setEnrollmentName] = useState("")
  const [enrollmentRelationship, setEnrollmentRelationship] = useState("")
  const [targetFaceId, setTargetFaceId] = useState<string | null>(null)
  const [enrollmentMessage, setEnrollmentMessage] = useState<string | null>(null)

  // Memory summaries mapped by person name (lowercase)
  const [personMemories, setPersonMemories] = useState<Record<string, string>>({})
  const faceFirstSeenRef = useRef<FaceTimestampMap>(new Map())
  const faceSessionIdRef = useRef("")
  const storedFaceIdsRef = useRef<Set<string>>(new Set())
  const storingFaceIdsRef = useRef<Set<string>>(new Set())
  const faceStorageRetryAtRef = useRef<Map<string, number>>(new Map())

  // MediaPipe BlazeFace detection for all faces in video
  const { detectedFaces, isLoading: isFaceDetectionLoading, error: faceDetectionError } = useFaceDetection(
    videoRef.current,
    {
      enabled: isStreaming && isVideoReady && !isRayBanMode,
      minDetectionConfidence: 0.35,
      targetFps: 12,
      useWorker: false,
    }
  )

  // Distinct voiceprints and conversation store state
  const [enrolledVoices, setEnrolledVoices] = useState<string[]>([])
  const [activeConversationPerson, setActiveConversationPerson] = useState<string | null>(null)
  const [personConversations, setPersonConversations] = useState<DistinctConversationEntry[]>([])
  const [isLoadingConversations, setIsLoadingConversations] = useState(false)

  // Multi-Face Recognition Hook: returns matches mapped by faceId and enrolled identities
  const {
    isLoading: isFaceRecognitionLoading,
    error: faceRecognitionError,
    matches: faceMatches,
    match: activeFaceMatch,
    enroll,
    loadIdentities,
    identities,
  } = useFaceRecognition(
    videoRef.current,
    isStreaming && isVideoReady && !isRayBanMode,
    detectedFaces
  )

  // List of all currently visible recognized names
  const visibleRecognizedNames = (Object.values(faceMatches) as FaceMatch[]).map((m) => m.name)

  // Server-side speech transcription & voice verification with per-speaker routing
  const {
    isListening,
    status: speechStatus,
    error: speechError,
    isVoiceVerified,
    lastSpeakerStatus,
    lastVerifiedSpeaker,
    calibrateVoice,
    isCalibrating,
    calibratingPerson,
    calibrationCountdown,
  } = useServerTranscription({
    enabled: isStreaming && !isMuted && Boolean(activeFaceMatch?.name || visibleRecognizedNames.length > 0),
    stream: streamRef.current,
    personName: activeFaceMatch?.name,
    candidateNames: visibleRecognizedNames,
    onTranscriptionComplete: useCallback(
      (res: { text: string; summary: string | null; speakerName: string | null }) => {
        // Crucial: strictly update the verified speaker's memory, never cross-contaminate!
        if (res.speakerName && res.summary) {
          const key = res.speakerName.toLowerCase()
          setPersonMemories((prev) => ({
            ...prev,
            [key]: res.summary!,
          }))
        }
      },
      []
    ),
  })

  // Synchronize enrolled voiceprint list
  const refreshVoiceList = useCallback(async () => {
    const list = await fetchEnrolledVoiceList()
    setEnrolledVoices(list.map((n) => n.toLowerCase()))
  }, [])

  useEffect(() => {
    void refreshVoiceList()
  }, [refreshVoiceList])

  const handleCalibrateVoice = async (personName: string) => {
    setEnrollmentMessage(`Calibrating voice for ${personName}... Please speak into microphone.`)
    const res = await calibrateVoice(personName)
    if (res.success) {
      setEnrollmentMessage(`✓ Voice calibrated successfully for ${personName}!`)
      void refreshVoiceList()
    } else {
      setEnrollmentMessage(res.error || `Voice calibration failed for ${personName}.`)
    }
  }

  const handleResetVoice = async (personName: string) => {
    await deleteEnrolledVoiceprint(personName)
    setEnrollmentMessage(`Voiceprint removed for ${personName}.`)
    void refreshVoiceList()
  }

  const handleViewConversations = async (personName: string) => {
    setActiveConversationPerson(personName)
    setIsLoadingConversations(true)
    const convs = await fetchPersonConversations(personName)
    setPersonConversations(convs)
    setIsLoadingConversations(false)
  }

  const handleClearPersonConversations = async (personName: string) => {
    await clearPersonConversations(personName)
    setPersonConversations([])
    setEnrollmentMessage(`Cleared conversation history for ${personName}.`)
  }

  // Enroll a specific individual (optionally targeted to a selected face)
  const enrollCurrentFace = async () => {
    const trimmedName = enrollmentName.trim()
    const trimmedRel = enrollmentRelationship.trim()
    if (!trimmedName) {
      setEnrollmentMessage("Please enter a name before enrolling.")
      return
    }

    const targetFace = targetFaceId ? detectedFaces.find((f) => f.id === targetFaceId) : null
    const targetBox = targetFace?.boundingBox

    const result = await enroll({
      name: trimmedName,
      relationship: trimmedRel || undefined,
      targetBox,
    })

    if (result.success) {
      const relLabel = trimmedRel ? ` (${trimmedRel})` : ""
      setEnrollmentMessage(`Enrolled ${trimmedName}${relLabel}. Click Calibrate Voice below to add voiceprint.`)
      setEnrollmentName("")
      setEnrollmentRelationship("")
      setTargetFaceId(null)
      void loadIdentities()
      void refreshVoiceList()
    } else {
      setEnrollmentMessage(result.error ?? "Enrollment failed.")
    }
  }

  // Wipe all profiles and identities
  const clearAllProfiles = async () => {
    try {
      if (typeof window !== "undefined") {
        window.localStorage.clear()
      }
      await fetch(`${INFERENCE_BACKEND_URL}/api/reset-all`, { method: "POST" })
      setEnrollmentMessage("All face data, voiceprints, and memories wiped clean.")
      setPersonMemories({})
      setTimeout(() => {
        if (typeof window !== "undefined") window.location.reload()
      }, 500)
    } catch (err) {
      setEnrollmentMessage("Failed to reset all data.")
    }
  }

  // Fetch memory summaries for each distinct recognized individual in view
  useEffect(() => {
    const names = (Object.values(faceMatches) as FaceMatch[]).map((m) => m.name.trim()).filter(Boolean)
    if (names.length === 0) return

    let cancelled = false
    names.forEach((name) => {
      const key = name.toLowerCase()
      if (personMemories[key]) return

      void fetch(`${INFERENCE_BACKEND_URL}/api/person-memories/${encodeURIComponent(name)}`)
        .then(async (response) => {
          if (!response.ok) throw new Error(`Memory lookup returned ${response.status}`)
          return response.json() as Promise<{ memory?: { summary?: string } | null }>
        })
        .then((body) => {
          if (!cancelled && body?.memory?.summary) {
            const summary = deduplicateSummary(body.memory.summary)
            if (summary) {
              setPersonMemories((prev) => ({ ...prev, [key]: summary }))
            }
          }
        })
        .catch((cause) => {
          console.warn("[PersonMemory] Lookup failed for", name, cause)
        })
    })

    return () => {
      cancelled = true
    }
  }, [faceMatches, personMemories])



  // Persist one downscaled crop after a face survives several frames
  useEffect(() => {
    const video = videoRef.current
    if (!video || !isStreaming || !isVideoReady) {
      return
    }

    detectedFaces
      .filter(
        (face) =>
          face.frameCount >= 5 &&
          !storedFaceIdsRef.current.has(face.id) &&
          !storingFaceIdsRef.current.has(face.id) &&
          (faceStorageRetryAtRef.current.get(face.id) ?? 0) <= Date.now()
      )
      .forEach((face) => {
        storingFaceIdsRef.current.add(face.id)

        void (async () => {
          try {
            if (!faceSessionIdRef.current) {
              faceSessionIdRef.current = crypto.randomUUID()
            }

            const imageDataUrl = captureFaceCrop(video, face)
            if (!imageDataUrl) {
              throw new Error("Unable to capture the detected face crop")
            }

            const response = await fetch(`${INFERENCE_BACKEND_URL}/api/faces/observations`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                session_id: faceSessionIdRef.current,
                face_id: face.id,
                confidence: face.confidence,
                bounding_box: face.boundingBox,
                image_data_url: imageDataUrl,
              }),
            })

            if (!response.ok) {
              throw new Error(`Face storage returned ${response.status}`)
            }

            storedFaceIdsRef.current.add(face.id)
            faceStorageRetryAtRef.current.delete(face.id)
            setFaceStorageError(null)
          } catch (cause) {
            const message = cause instanceof Error ? cause.message : "Face storage failed"
            console.error("[FaceDetection] Failed to store face observation:", cause)
            setFaceStorageError(message)
            faceStorageRetryAtRef.current.set(face.id, Date.now() + 5_000)
          } finally {
            storingFaceIdsRef.current.delete(face.id)
          }
        })()
      })
  }, [detectedFaces, isStreaming, isVideoReady])

  // Record first-seen timestamps for new faces
  useEffect(() => {
    if (detectedFaces.length === 0) return
    const now = Date.now()
    detectedFaces.forEach((face) => {
      if (!faceFirstSeenRef.current.has(face.id)) {
        faceFirstSeenRef.current.set(face.id, now)
      }
    })
  }, [detectedFaces])

  // Periodically check if any faces should be marked as unidentified
  useEffect(() => {
    const interval = setInterval(() => {
      const now = Date.now()
      setUnidentifiedFaceIds((prev) => {
        const next = new Set(prev)
        for (const [faceId, firstSeen] of faceFirstSeenRef.current.entries()) {
          // Only mark unidentified if not recognized by face recognition
          if (now - firstSeen >= UNIDENTIFIED_TIMEOUT_MS && !faceMatches[faceId]) {
            next.add(faceId)
          } else if (faceMatches[faceId]) {
            next.delete(faceId)
          }
        }
        return next
      })
    }, 1000)

    return () => clearInterval(interval)
  }, [faceMatches])

  // Clean up lost faces
  useEffect(() => {
    const currentFaceIds = new Set(detectedFaces.map((f) => f.id))
    setUnidentifiedFaceIds((prev) => {
      const next = new Set(prev)
      for (const faceId of next) {
        if (!currentFaceIds.has(faceId)) {
          next.delete(faceId)
        }
      }
      return next
    })
    for (const faceId of faceFirstSeenRef.current.keys()) {
      if (!currentFaceIds.has(faceId)) {
        faceFirstSeenRef.current.delete(faceId)
      }
    }
  }, [detectedFaces])

  // Start webcam on mount
  useEffect(() => {
    startWebcam()

    return () => {
      stopWebcam()
    }
  }, [])

  // High-fidelity AR Glass simulation stream using Canvas MediaStream
  const startSimulationStream = useCallback((preset: string = "sarah_jenkins") => {
    try {
      console.log(`[Webcam] Starting AR simulation stream with preset: ${preset}`)
      setSimPreset(preset)
      setCameraError(null)

      if (simulationIntervalRef.current) {
        clearInterval(simulationIntervalRef.current)
        simulationIntervalRef.current = null
      }

      if (!simulationCanvasRef.current) {
        const c = document.createElement("canvas")
        c.width = 1280
        c.height = 720
        simulationCanvasRef.current = c
      }

      const canvas = simulationCanvasRef.current
      const ctx = canvas.getContext("2d")
      if (!ctx) return

      const img = new Image()
      img.crossOrigin = "anonymous"
      const sampleMap: Record<string, string> = {
        sarah_jenkins: "/samples/sarah_jenkins.jpg",
        dr_thorne: "/samples/dr_thorne.jpg",
        marcus_vance: "/samples/marcus_vance.jpg",
        group: "/samples/group_sarah_and_colleague.jpg",
      }
      img.src = sampleMap[preset] || "/samples/sarah_jenkins.jpg"

      let t = 0
      img.onload = () => {
        const renderFrame = () => {
          t += 0.03
          ctx.clearRect(0, 0, canvas.width, canvas.height)

          const zoom = 1.0 + Math.sin(t) * 0.012
          const dx = Math.sin(t * 0.7) * 3
          const dy = Math.cos(t * 0.5) * 2

          const dw = canvas.width * zoom
          const dh = canvas.height * zoom
          const ox = (canvas.width - dw) / 2 + dx
          const oy = (canvas.height - dh) / 2 + dy

          ctx.drawImage(img, ox, oy, dw, dh)
        }

        renderFrame()
        simulationIntervalRef.current = setInterval(renderFrame, 33)

        const stream = (canvas as any).captureStream ? (canvas as any).captureStream(30) : null
        if (stream && videoRef.current) {
          const video = videoRef.current
          video.srcObject = stream
          streamRef.current = stream
          video.play().catch(console.warn)
          setIsStreaming(true)
          setIsVideoReady(true)
          setIsSimulatedStream(true)
          console.log("[Webcam] Simulation stream active and bound to videoRef")
        }
      }
    } catch (e) {
      console.error("[Webcam] Simulation stream failed:", e)
    }
  }, [])

  // Robust webcam initialization with fallback for constrained devices or missing audio
  const startWebcam = async () => {
    try {
      console.log("[Webcam] Requesting media access...")
      setCameraError(null)

      if (simulationIntervalRef.current) {
        clearInterval(simulationIntervalRef.current)
        simulationIntervalRef.current = null
      }
      setIsSimulatedStream(false)

      let stream: MediaStream | null = null
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: true,
        })
      } catch (firstErr) {
        console.warn("[Webcam] Standard audio+HD constraints failed, falling back to video-only:", firstErr)
        try {
          stream = await navigator.mediaDevices.getUserMedia({
            video: true,
            audio: false,
          })
        } catch (secondErr) {
          console.error("[Webcam] Video fallback also failed:", secondErr)
          throw secondErr
        }
      }

      if (videoRef.current && stream) {
        const video = videoRef.current

        const handleMetadataLoaded = () => {
          console.log("[Webcam] Video metadata loaded:", {
            width: video.videoWidth,
            height: video.videoHeight,
          })
          setIsVideoReady(true)
        }

        video.addEventListener("loadedmetadata", handleMetadataLoaded)

        if (video.videoWidth > 0 && video.videoHeight > 0) {
          handleMetadataLoaded()
        }

        video.srcObject = stream
        streamRef.current = stream

        // Ensure video playback starts cleanly
        video.play().catch((playErr) => {
          console.warn("[Webcam] Autoplay play() rejected:", playErr)
        })

        stream.getAudioTracks().forEach((track) => {
          track.enabled = !isMuted
        })
        setIsStreaming(true)
        console.log("[Webcam] Stream started successfully")
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Error accessing webcam"
      console.error("[Webcam] Error accessing webcam:", err)
      setCameraError(`Unable to access camera: ${msg}. Launching simulated AR Glass feed...`)
      // Seamlessly fallback to simulation stream so AR Glass experience never stays black
      setTimeout(() => {
        startSimulationStream("sarah_jenkins")
      }, 250)
    }
  }

  const stopWebcam = () => {
    console.log("[Webcam] Stopping stream")

    if (simulationIntervalRef.current) {
      clearInterval(simulationIntervalRef.current)
      simulationIntervalRef.current = null
    }
    setIsSimulatedStream(false)

    if (videoRef.current?.srcObject) {
      const stream = videoRef.current.srcObject as MediaStream
      stream.getTracks().forEach((track) => track.stop())
      videoRef.current.srcObject = null
    }

    streamRef.current = null
    setIsStreaming(false)
    setIsVideoReady(false)
    setIsRayBanMode(false)
    setIsMuted(false)
    storedFaceIdsRef.current.clear()
    storingFaceIdsRef.current.clear()
    faceStorageRetryAtRef.current.clear()
    faceSessionIdRef.current = ""
  }

  const toggleMute = useCallback(() => {
    const stream = streamRef.current
    if (!stream) {
      return
    }
    setIsMuted((prev) => {
      const next = !prev
      stream.getAudioTracks().forEach((track) => {
        track.enabled = !next
      })
      return next
    })
  }, [])

  // Map each detected face into an on-screen HUD notification
  const faceNotifications = detectedFaces
    .map((face) => {
      const video = videoRef.current
      const overlay = overlayRef.current

      if (!video || !overlay) return null

      const videoWidth = video.videoWidth
      const videoHeight = video.videoHeight
      const overlayWidth = overlay.clientWidth
      const overlayHeight = overlay.clientHeight

      if (videoWidth === 0 || videoHeight === 0) return null

      const transform = calculateVideoTransform(
        videoWidth,
        videoHeight,
        overlayWidth,
        overlayHeight
      )

      const overlayBox = mapBoundingBoxToOverlay(
        face.boundingBox,
        transform,
        overlayWidth,
        true
      )

      const position = calculateNotificationPosition(
        overlayBox,
        overlayWidth,
        overlayHeight
      )

      return {
        face,
        position,
        overlayBox,
      }
    })
    .filter((n): n is NonNullable<typeof n> => n !== null)

  const recognizedCount = Object.keys(faceMatches).length

  return (
    <div
      className="relative h-screen w-screen overflow-hidden bg-black select-none"
      style={
        {
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'SF Pro Text', 'Helvetica Neue', Arial, sans-serif",
          WebkitFontSmoothing: "antialiased",
        } as React.CSSProperties
      }
    >
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        className={cn(
          "absolute inset-0 h-full w-full object-cover transition-all duration-300",
          isRayBanMode ? "scale-[1.08] blur-[13px]" : "scale-100"
        )}
        style={{ transform: "scaleX(-1)" }}
      />

      {/* Stream Mode Top HUD Badge */}
      <div
        style={{
          position: "absolute",
          top: 18,
          left: 18,
          zIndex: 50,
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        {isSimulatedStream ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "6px 14px",
              borderRadius: 20,
              background: "rgba(15, 23, 42, 0.82)",
              border: "1px solid rgba(56, 189, 248, 0.4)",
              backdropFilter: "blur(14px)",
              color: "#38bdf8",
              fontSize: 12,
              fontWeight: 600,
              boxShadow: "0 4px 20px rgba(0, 0, 0, 0.5)",
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: "#38bdf8",
                boxShadow: "0 0 10px #38bdf8",
              }}
            />
            <span>AR Glass Simulation Feed</span>
            <select
              value={simPreset}
              onChange={(e) => startSimulationStream(e.target.value)}
              style={{
                background: "rgba(2, 6, 23, 0.8)",
                border: "1px solid rgba(56, 189, 248, 0.35)",
                color: "#e2e8f0",
                fontSize: 11.5,
                fontWeight: 600,
                borderRadius: 8,
                padding: "3px 8px",
                outline: "none",
                cursor: "pointer",
              }}
            >
              <option value="sarah_jenkins">Sarah Jenkins (Daughter)</option>
              <option value="dr_thorne">Dr. Aris Thorne (Physician)</option>
              <option value="marcus_vance">Marcus Vance (Partner)</option>
              <option value="group">Group (Sarah & Colleague)</option>
            </select>
            <button
              onClick={() => {
                stopWebcam()
                void startWebcam()
              }}
              style={{
                background: "rgba(255, 255, 255, 0.1)",
                border: "1px solid rgba(255, 255, 255, 0.2)",
                color: "#fff",
                fontSize: 11,
                fontWeight: 600,
                borderRadius: 8,
                padding: "3px 10px",
                cursor: "pointer",
                transition: "all 0.2s",
              }}
            >
              Use Physical Camera
            </button>
          </div>
        ) : isStreaming ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "6px 14px",
              borderRadius: 20,
              background: "rgba(15, 23, 42, 0.82)",
              border: "1px solid rgba(16, 185, 129, 0.4)",
              backdropFilter: "blur(14px)",
              color: "#34d399",
              fontSize: 12,
              fontWeight: 600,
              boxShadow: "0 4px 20px rgba(0, 0, 0, 0.5)",
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: "#10b981",
                boxShadow: "0 0 10px #10b981",
              }}
            />
            <span>Live Camera Connected</span>
            <button
              onClick={() => startSimulationStream("sarah_jenkins")}
              style={{
                background: "rgba(255, 255, 255, 0.1)",
                border: "1px solid rgba(255, 255, 255, 0.2)",
                color: "#fff",
                fontSize: 11,
                fontWeight: 600,
                borderRadius: 8,
                padding: "3px 10px",
                cursor: "pointer",
                marginLeft: 4,
              }}
            >
              Switch to Simulation
            </button>
          </div>
        ) : null}
      </div>

      {/* Camera error fallback overlay */}
      {cameraError && !isStreaming && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            background: "rgba(0,0,0,0.85)",
            zIndex: 60,
            padding: 24,
            textAlign: "center",
          }}
        >
          <div
            style={{
              maxWidth: 460,
              padding: "28px 32px",
              borderRadius: 22,
              background: "rgba(15, 23, 42, 0.88)",
              backdropFilter: "blur(24px)",
              WebkitBackdropFilter: "blur(24px)",
              border: "1px solid rgba(56, 189, 248, 0.35)",
              boxShadow: "0 12px 40px rgba(0,0,0,0.7)",
            }}
          >
            <div style={{ fontSize: 36, marginBottom: 12 }}>👓</div>
            <h3 style={{ color: "#fff", fontSize: 18, fontWeight: 700, margin: "0 0 8px" }}>
              AR Smart Glass Stream
            </h3>
            <p style={{ color: "rgba(255,255,255,0.72)", fontSize: 13, lineHeight: 1.5, margin: "0 0 20px" }}>
              {cameraError}
            </p>
            <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
              <button
                onClick={() => {
                  startSimulationStream("sarah_jenkins")
                }}
                style={{
                  padding: "10px 22px",
                  borderRadius: 12,
                  background: "linear-gradient(135deg, #0284c7, #0369a1)",
                  color: "#fff",
                  border: "none",
                  fontSize: 13.5,
                  fontWeight: 600,
                  cursor: "pointer",
                  boxShadow: "0 0 16px rgba(2, 132, 199, 0.5)",
                }}
              >
                ✨ Launch AR Simulation Stream
              </button>
              <button
                onClick={() => {
                  setCameraError(null)
                  void startWebcam()
                }}
                style={{
                  padding: "10px 20px",
                  borderRadius: 12,
                  background: "rgba(255,255,255,0.1)",
                  color: "#fff",
                  border: "1px solid rgba(255,255,255,0.2)",
                  fontSize: 13.5,
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Retry Physical Camera
              </button>
            </div>
          </div>
        </div>
      )}

      {!isRayBanMode && (
        <>
          {/* ── Multi-Face HUD Overlays: Each individual gets their own card & distinction ── */}
          <div ref={overlayRef} className="absolute inset-0 pointer-events-none">
            {faceNotifications.map((notification) => {
              const faceId = notification.face.id
              const matchForFace = faceMatches[faceId]
              const isRecognized = Boolean(matchForFace)
              const isUnidentified = !isRecognized && unidentifiedFaceIds.has(faceId)
              const isTargeted = targetFaceId === faceId

              // Personalized memory summary for this specific individual
              const personKey = matchForFace?.name?.toLowerCase()
              const personMemory =
                (personKey && personMemories[personKey]) ||
                matchForFace?.description ||
                undefined

              return (
                <div
                  key={faceId}
                  onClick={() => setTargetFaceId((prev) => (prev === faceId ? null : faceId))}
                  style={{
                    pointerEvents: "auto",
                    cursor: "pointer",
                    outline: isTargeted ? "2px solid #0a84ff" : "none",
                    borderRadius: 14,
                  }}
                  title="Click to target this person for enrollment or update"
                >
                  <FaceNotification
                    faceId={faceId}
                    box={notification.overlayBox}
                    left={notification.position.left}
                    top={notification.position.top}
                    confidence={notification.face.confidence}
                    name={isRecognized ? matchForFace?.name : undefined}
                    relationship={isRecognized ? matchForFace?.relationship : undefined}
                    description={isRecognized ? personMemory : undefined}
                    isUnidentified={isUnidentified}
                  />
                </div>
              )
            })}
          </div>

          {/* ── Top-right: camera status & multi-person tally pill ── */}
          <div
            style={
              {
                position: "absolute",
                top: 16,
                right: 16,
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "6px 14px",
                borderRadius: 24,
                background: "rgba(0,0,0,0.55)",
                backdropFilter: "blur(20px)",
                WebkitBackdropFilter: "blur(20px)",
                border: "1px solid rgba(255,255,255,0.12)",
                boxShadow: "0 2px 14px rgba(0,0,0,0.4)",
                zIndex: 50,
              } as React.CSSProperties
            }
          >
            <span
              style={{
                width: 7,
                height: 7,
                borderRadius: "50%",
                background: isStreaming ? "#30d158" : "#ff453a",
                boxShadow: isStreaming ? "0 0 8px #30d158" : "none",
                flexShrink: 0,
              }}
            />
            <span
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: "rgba(255,255,255,0.9)",
                textShadow: "0 1px 4px rgba(0,0,0,0.9)",
              }}
            >
              {isStreaming
                ? detectedFaces.length > 0
                  ? `Camera Live • ${detectedFaces.length} Face${detectedFaces.length > 1 ? "s" : ""} (${recognizedCount} ID'd)`
                  : "Camera Live • Scanning"
                : "Camera Off"}
            </span>
          </div>

          {/* ── Top-right: speech / speaker identification status ── */}
          <div
            style={
              {
                position: "absolute",
                top: 54,
                right: 16,
                maxWidth: 260,
                padding: "6px 14px",
                borderRadius: 14,
                background: "rgba(0,0,0,0.52)",
                backdropFilter: "blur(18px)",
                WebkitBackdropFilter: "blur(18px)",
                border: "1px solid rgba(255,255,255,0.09)",
                zIndex: 50,
              } as React.CSSProperties
            }
          >
            <span
              style={{
                fontSize: 11.5,
                fontWeight: 500,
                color: "rgba(255,255,255,0.68)",
                textShadow: "0 1px 3px rgba(0,0,0,0.9)",
                lineHeight: 1.4,
              }}
            >
              {recognizedCount === 0
                ? "Recognize or enroll individuals to track memory"
                : speechStatus === "transcribing"
                ? "✦ Transcribing & distilling speech…"
                : isListening
                ? "● Listening to conversation…"
                : isMuted
                ? "Mic paused"
                : `Ready • ${recognizedCount} individual${recognizedCount > 1 ? "s" : ""} in scene`}
            </span>
          </div>

          {/* ── Top-left: Multi-Individual Enrollment Panel ── */}
          <div
            style={
              {
                position: "absolute",
                top: 80,
                left: 16,
                width: 290,
                borderRadius: 20,
                background: "rgba(0,0,0,0.64)",
                backdropFilter: "blur(26px)",
                WebkitBackdropFilter: "blur(26px)",
                border: "1px solid rgba(255,255,255,0.12)",
                boxShadow: "0 8px 32px rgba(0,0,0,0.5), 0 0 0 0.5px rgba(255,255,255,0.06)",
                padding: "16px 16px",
                zIndex: 50,
              } as React.CSSProperties
            }
          >
            {/* Panel header */}
            <div style={{ marginBottom: 10 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <p
                  style={{
                    margin: 0,
                    fontSize: 13.5,
                    fontWeight: 700,
                    color: "#fff",
                    letterSpacing: "-0.2px",
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                  }}
                >
                  <Users style={{ width: 15, height: 15, color: "#0a84ff" }} />
                  Enroll Individual
                </p>
                {targetFaceId && (
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 600,
                      padding: "2px 7px",
                      borderRadius: 10,
                      background: "rgba(10,132,255,0.25)",
                      color: "#64b5f6",
                      border: "1px solid rgba(10,132,255,0.4)",
                    }}
                  >
                    Targeting {targetFaceId}
                  </span>
                )}
              </div>
              <p
                style={{
                  margin: "4px 0 0",
                  fontSize: 11,
                  fontWeight: 400,
                  color: "rgba(255,255,255,0.52)",
                  lineHeight: 1.35,
                }}
              >
                {isFaceRecognitionLoading
                  ? "Loading recognition neural network…"
                  : detectedFaces.length > 1
                  ? "Multiple faces detected. Select a face or enter name & relationship:"
                  : "Keep face visible, enter identity info and enroll:"}
              </p>
            </div>

            {/* Target Face Selector if multiple faces are in view */}
            {detectedFaces.length > 1 && (
              <div style={{ display: "flex", gap: 5, marginBottom: 10, overflowX: "auto" }}>
                {detectedFaces.map((f, i) => {
                  const isSel = targetFaceId === f.id
                  const fMatch = faceMatches[f.id]
                  return (
                    <button
                      key={f.id}
                      onClick={() => setTargetFaceId(isSel ? null : f.id)}
                      style={{
                        padding: "4px 8px",
                        borderRadius: 8,
                        background: isSel ? "rgba(10,132,255,0.4)" : "rgba(255,255,255,0.08)",
                        border: isSel ? "1px solid #0a84ff" : "1px solid rgba(255,255,255,0.12)",
                        color: isSel ? "#fff" : "rgba(255,255,255,0.7)",
                        fontSize: 11,
                        fontWeight: 500,
                        cursor: "pointer",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {fMatch ? `✓ ${fMatch.name}` : `Face #${i + 1}`}
                    </button>
                  )
                })}
              </div>
            )}

            {/* Divider */}
            <div
              style={{
                height: 1,
                background: "linear-gradient(to right, transparent, rgba(255,255,255,0.10), transparent)",
                marginBottom: 10,
              }}
            />

            {/* Input fields */}
            <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
              <input
                value={enrollmentName}
                onChange={(e) => setEnrollmentName(e.target.value)}
                placeholder="Name (e.g. Sarah)"
                style={
                  {
                    width: "100%",
                    padding: "7px 11px",
                    borderRadius: 10,
                    background: "rgba(255,255,255,0.08)",
                    border: "1px solid rgba(255,255,255,0.14)",
                    color: "#fff",
                    fontSize: 12,
                    fontWeight: 500,
                    outline: "none",
                  } as React.CSSProperties
                }
                onFocus={(e) => {
                  e.currentTarget.style.border = "1px solid rgba(10,132,255,0.7)"
                }}
                onBlur={(e) => {
                  e.currentTarget.style.border = "1px solid rgba(255,255,255,0.14)"
                }}
              />

              <input
                value={enrollmentRelationship}
                onChange={(e) => setEnrollmentRelationship(e.target.value)}
                placeholder="Relationship (e.g. Daughter, Doctor, Friend)"
                style={
                  {
                    width: "100%",
                    padding: "7px 11px",
                    borderRadius: 10,
                    background: "rgba(255,255,255,0.08)",
                    border: "1px solid rgba(255,255,255,0.14)",
                    color: "#fff",
                    fontSize: 12,
                    fontWeight: 500,
                    outline: "none",
                  } as React.CSSProperties
                }
                onFocus={(e) => {
                  e.currentTarget.style.border = "1px solid rgba(10,132,255,0.7)"
                }}
                onBlur={(e) => {
                  e.currentTarget.style.border = "1px solid rgba(255,255,255,0.14)"
                }}
              />

              {/* Quick Demo Pre-fill helpers */}
              <div style={{ display: "flex", gap: 5, marginTop: 2 }}>
                <button
                  type="button"
                  onClick={() => {
                    setEnrollmentName("Sarah")
                    setEnrollmentRelationship("Your daughter")
                  }}
                  style={{
                    flex: 1,
                    padding: "4px 6px",
                    borderRadius: 7,
                    background: "rgba(255,255,255,0.05)",
                    border: "1px solid rgba(255,255,255,0.10)",
                    color: "rgba(255,255,255,0.6)",
                    fontSize: 10,
                    cursor: "pointer",
                  }}
                >
                  + Sarah (Daughter)
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setEnrollmentName("Michael")
                    setEnrollmentRelationship("Your son")
                  }}
                  style={{
                    flex: 1,
                    padding: "4px 6px",
                    borderRadius: 7,
                    background: "rgba(255,255,255,0.05)",
                    border: "1px solid rgba(255,255,255,0.10)",
                    color: "rgba(255,255,255,0.6)",
                    fontSize: 10,
                    cursor: "pointer",
                  }}
                >
                  + Michael (Son)
                </button>
              </div>

              <button
                onClick={enrollCurrentFace}
                disabled={isFaceRecognitionLoading || !isStreaming || !enrollmentName.trim()}
                style={
                  {
                    marginTop: 4,
                    padding: "8px 14px",
                    borderRadius: 10,
                    background:
                      isFaceRecognitionLoading || !isStreaming || !enrollmentName.trim()
                        ? "rgba(10,132,255,0.3)"
                        : "rgba(10,132,255,0.9)",
                    border: "none",
                    color:
                      isFaceRecognitionLoading || !isStreaming || !enrollmentName.trim()
                        ? "rgba(255,255,255,0.4)"
                        : "#fff",
                    fontSize: 12.5,
                    fontWeight: 600,
                    cursor:
                      isFaceRecognitionLoading || !isStreaming || !enrollmentName.trim()
                        ? "not-allowed"
                        : "pointer",
                    transition: "background 200ms, transform 100ms",
                    boxShadow: "0 2px 10px rgba(10,132,255,0.3)",
                  } as React.CSSProperties
                }
              >
                Enroll Individual
              </button>
            </div>

            {/* Clear profiles button */}
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }}>
              <button
                onClick={clearAllProfiles}
                style={{
                  background: "none",
                  border: "none",
                  color: "rgba(255,107,107,0.75)",
                  fontSize: 11,
                  fontWeight: 500,
                  cursor: "pointer",
                  textDecoration: "underline",
                  padding: "2px 4px",
                }}
              >
                Reset All Memories & Faces
              </button>
            </div>

            {/* Enrolled Profiles & Distinct Voiceprints Section */}
            <div style={{ marginTop: 14 }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  marginBottom: 8,
                }}
              >
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    textTransform: "uppercase",
                    letterSpacing: "0.5px",
                    color: "rgba(255,255,255,0.5)",
                  }}
                >
                  Enrolled Profiles & Voiceprints
                </span>
                <button
                  onClick={() => {
                    void loadIdentities()
                    void refreshVoiceList()
                  }}
                  title="Refresh identities and voiceprints"
                  style={{
                    background: "none",
                    border: "none",
                    color: "rgba(255,255,255,0.4)",
                    cursor: "pointer",
                    padding: 2,
                    display: "flex",
                    alignItems: "center",
                  }}
                >
                  <RefreshCw style={{ width: 11, height: 11 }} />
                </button>
              </div>

              {identities && identities.length > 0 ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 180, overflowY: "auto" }}>
                  {identities.map((id) => {
                    const hasVoice = enrolledVoices.includes(id.name.toLowerCase())
                    return (
                      <div
                        key={id.name}
                        style={{
                          padding: "7px 9px",
                          borderRadius: 9,
                          background: "rgba(255,255,255,0.04)",
                          border: "1px solid rgba(255,255,255,0.08)",
                          display: "flex",
                          flexDirection: "column",
                          gap: 4,
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                          <div>
                            <span style={{ fontSize: 12, fontWeight: 600, color: "#fff" }}>{id.name}</span>
                            {id.relationship && (
                              <span style={{ fontSize: 11, color: "#64b5f6", marginLeft: 6 }}>({id.relationship})</span>
                            )}
                          </div>
                          <span
                            style={{
                              fontSize: 10,
                              fontWeight: 500,
                              padding: "2px 6px",
                              borderRadius: 6,
                              background: hasVoice ? "rgba(48,209,88,0.15)" : "rgba(255,159,10,0.15)",
                              color: hasVoice ? "#30d158" : "#ff9f0a",
                              border: hasVoice ? "1px solid rgba(48,209,88,0.3)" : "1px solid rgba(255,159,10,0.3)",
                            }}
                          >
                            {hasVoice ? "✓ Voice Enrolled" : "⚠️ No Voiceprint"}
                          </span>
                        </div>

                        <div style={{ display: "flex", gap: 5, marginTop: 2 }}>
                          <button
                            onClick={() => handleCalibrateVoice(id.name)}
                            disabled={!isStreaming || isCalibrating}
                            style={{
                              flex: 1,
                              padding: "4px 8px",
                              borderRadius: 6,
                              background: "rgba(10,132,255,0.2)",
                              border: "1px solid rgba(10,132,255,0.4)",
                              color: "#64b5f6",
                              fontSize: 10.5,
                              fontWeight: 600,
                              cursor: !isStreaming || isCalibrating ? "not-allowed" : "pointer",
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                              gap: 4,
                            }}
                          >
                            <Mic style={{ width: 10, height: 10 }} />
                            {hasVoice ? "Re-Calibrate" : "Calibrate Voice"}
                          </button>

                          <button
                            onClick={() => handleViewConversations(id.name)}
                            style={{
                              padding: "4px 8px",
                              borderRadius: 6,
                              background: "rgba(255,255,255,0.08)",
                              border: "1px solid rgba(255,255,255,0.14)",
                              color: "rgba(255,255,255,0.8)",
                              fontSize: 10.5,
                              fontWeight: 500,
                              cursor: "pointer",
                              display: "flex",
                              alignItems: "center",
                              gap: 4,
                            }}
                          >
                            <MessageSquare style={{ width: 10, height: 10 }} />
                            History
                          </button>

                          {hasVoice && (
                            <button
                              onClick={() => handleResetVoice(id.name)}
                              title="Delete voiceprint"
                              style={{
                                padding: "4px 6px",
                                borderRadius: 6,
                                background: "rgba(255,59,48,0.15)",
                                border: "1px solid rgba(255,59,48,0.25)",
                                color: "#ff6b6b",
                                fontSize: 10,
                                cursor: "pointer",
                              }}
                            >
                              ↺
                            </button>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <p style={{ fontSize: 11, color: "rgba(255,255,255,0.4)", fontStyle: "italic", margin: 0 }}>
                  No enrolled individuals yet. Enroll a face above.
                </p>
              )}
            </div>

            {enrollmentMessage && (
              <p
                style={{
                  margin: "8px 0 0",
                  fontSize: 11.5,
                  fontWeight: 500,
                  color: enrollmentMessage.startsWith("Enrolled") ? "#30d158" : "#ff9f0a",
                  textShadow: "0 1px 3px rgba(0,0,0,0.8)",
                  display: "flex",
                  alignItems: "center",
                  gap: 5,
                }}
              >
                {enrollmentMessage.startsWith("Enrolled") ? (
                  <CheckCircle2 style={{ width: 13, height: 13, flexShrink: 0 }} />
                ) : (
                  <AlertCircle style={{ width: 13, height: 13, flexShrink: 0 }} />
                )}
                {enrollmentMessage}
              </p>
            )}
          </div>

          {/* ── Top-left: AI init / error pills ── */}
          {isFaceDetectionLoading && (
            <div
              style={
                {
                  position: "absolute",
                  top: 16,
                  left: 16,
                  display: "flex",
                  alignItems: "center",
                  gap: 7,
                  padding: "6px 14px",
                  borderRadius: 24,
                  background: "rgba(0,0,0,0.55)",
                  backdropFilter: "blur(20px)",
                  WebkitBackdropFilter: "blur(20px)",
                  border: "1px solid rgba(10,132,255,0.25)",
                  boxShadow: "0 2px 14px rgba(10,132,255,0.15)",
                  zIndex: 50,
                } as React.CSSProperties
              }
            >
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: "#0a84ff",
                  boxShadow: "0 0 8px #0a84ff",
                  animation: "pulse 1.5s infinite",
                  flexShrink: 0,
                }}
              />
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 500,
                  color: "#64b5f6",
                  textShadow: "0 1px 4px rgba(0,0,0,0.9)",
                }}
              >
                Initializing Vision AI…
              </span>
            </div>
          )}

          {faceDetectionError && (
            <div
              style={
                {
                  position: "absolute",
                  top: 16,
                  left: 16,
                  padding: "6px 13px",
                  borderRadius: 24,
                  background: "rgba(255,59,48,0.12)",
                  backdropFilter: "blur(16px)",
                  border: "1px solid rgba(255,59,48,0.25)",
                  zIndex: 50,
                } as React.CSSProperties
              }
            >
              <span style={{ fontSize: 11.5, color: "#ff6b6b", textShadow: "0 1px 4px rgba(0,0,0,0.9)" }}>
                ⚠ {faceDetectionError}
              </span>
            </div>
          )}

          {faceStorageError && (
            <div
              style={
                {
                  position: "absolute",
                  top: 48,
                  left: 16,
                  padding: "6px 13px",
                  borderRadius: 24,
                  background: "rgba(255,59,48,0.10)",
                  backdropFilter: "blur(16px)",
                  border: "1px solid rgba(255,59,48,0.20)",
                  zIndex: 50,
                } as React.CSSProperties
              }
            >
              <span
                style={{
                  fontSize: 11.5,
                  color: "rgba(255,107,107,0.85)",
                  textShadow: "0 1px 4px rgba(0,0,0,0.9)",
                }}
              >
                ⚠ {faceStorageError}
              </span>
            </div>
          )}

          {faceRecognitionError && (
            <div
              style={
                {
                  position: "absolute",
                  top: faceStorageError ? 80 : 48,
                  left: 16,
                  padding: "6px 13px",
                  borderRadius: 24,
                  background: "rgba(255,59,48,0.10)",
                  backdropFilter: "blur(16px)",
                  border: "1px solid rgba(255,59,48,0.20)",
                  zIndex: 50,
                } as React.CSSProperties
              }
            >
              <span
                style={{
                  fontSize: 11.5,
                  color: "rgba(255,107,107,0.85)",
                  textShadow: "0 1px 4px rgba(0,0,0,0.9)",
                }}
              >
                ⚠ {faceRecognitionError}
              </span>
            </div>
          )}

          {speechError && (
            <div
              style={
                {
                  position: "absolute",
                  top: 92,
                  right: 16,
                  padding: "6px 13px",
                  borderRadius: 24,
                  background: "rgba(255,59,48,0.10)",
                  backdropFilter: "blur(16px)",
                  border: "1px solid rgba(255,59,48,0.20)",
                  zIndex: 50,
                } as React.CSSProperties
              }
            >
              <span
                style={{
                  fontSize: 11.5,
                  color: "rgba(255,107,107,0.85)",
                  textShadow: "0 1px 4px rgba(0,0,0,0.9)",
                }}
              >
                ⚠ {speechError}
              </span>
            </div>
          )}

          {lastSpeakerStatus && (
            <div
              style={
                {
                  position: "absolute",
                  top: 16,
                  right: 280,
                  display: "flex",
                  alignItems: "center",
                  gap: 7,
                  padding: "6px 14px",
                  borderRadius: 24,
                  background: isVoiceVerified ? "rgba(48,209,88,0.15)" : "rgba(255,159,10,0.15)",
                  backdropFilter: "blur(20px)",
                  WebkitBackdropFilter: "blur(20px)",
                  border: isVoiceVerified
                    ? "1px solid rgba(48,209,88,0.35)"
                    : "1px solid rgba(255,159,10,0.35)",
                  boxShadow: isVoiceVerified
                    ? "0 2px 14px rgba(48,209,88,0.2)"
                    : "0 2px 14px rgba(255,159,10,0.2)",
                  zIndex: 50,
                } as React.CSSProperties
              }
            >
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: isVoiceVerified ? "#30d158" : "#ff9f0a",
                  boxShadow: `0 0 8px ${isVoiceVerified ? "#30d158" : "#ff9f0a"}`,
                  flexShrink: 0,
                }}
              />
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  color: isVoiceVerified ? "#30d158" : "#ff9f0a",
                  textShadow: "0 1px 4px rgba(0,0,0,0.9)",
                }}
              >
                {lastSpeakerStatus}
              </span>
            </div>
          )}
        </>
      )}

      <RayBanOverlay stream={streamRef.current} videoRef={videoRef} visible={isRayBanMode} />

      {/* ── Bottom dock ── */}
      <div
        style={
          {
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            padding: "20px 24px 28px",
            background:
              "linear-gradient(to top, rgba(0,0,0,0.75) 0%, rgba(0,0,0,0.2) 70%, transparent 100%)",
            zIndex: 50,
            pointerEvents: "auto",
          } as React.CSSProperties
        }
      >
        <div
          style={
            {
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "10px 18px",
              borderRadius: 40,
              background: "rgba(0,0,0,0.62)",
              backdropFilter: "blur(28px)",
              WebkitBackdropFilter: "blur(28px)",
              border: "1px solid rgba(255,255,255,0.10)",
              boxShadow: "0 8px 32px rgba(0,0,0,0.5), 0 0 0 0.5px rgba(255,255,255,0.05)",
            } as React.CSSProperties
          }
        >
          {/* Mic button */}
          <button
            onClick={toggleMute}
            disabled={!isStreaming}
            style={
              {
                width: 44,
                height: 44,
                borderRadius: "50%",
                background: isMuted ? "rgba(255,59,48,0.75)" : "rgba(255,255,255,0.10)",
                border: isMuted
                  ? "1px solid rgba(255,59,48,0.5)"
                  : "1px solid rgba(255,255,255,0.14)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                cursor: !isStreaming ? "not-allowed" : "pointer",
                opacity: !isStreaming ? 0.4 : 1,
                transition: "background 200ms, border 200ms, transform 150ms",
                boxShadow: isMuted ? "0 0 16px rgba(255,59,48,0.3)" : "none",
              } as React.CSSProperties
            }
            onMouseEnter={(e) => {
              if (isStreaming) (e.currentTarget as HTMLButtonElement).style.transform = "scale(1.08)"
            }}
            onMouseLeave={(e) => {
              ;(e.currentTarget as HTMLButtonElement).style.transform = "scale(1)"
            }}
            aria-pressed={isMuted}
          >
            {isMuted ? (
              <MicOff style={{ width: 18, height: 18, color: "#fff" }} />
            ) : (
              <Mic style={{ width: 18, height: 18, color: "rgba(255,255,255,0.9)" }} />
            )}
          </button>
          <span
            style={{
              fontSize: 11.5,
              fontWeight: 500,
              color: "rgba(255,255,255,0.55)",
              letterSpacing: "-0.1px",
              textShadow: "0 1px 3px rgba(0,0,0,0.8)",
              minWidth: 84,
            }}
          >
            {isMuted
              ? "Mic off"
              : recognizedCount === 0
              ? "Waiting"
              : isListening
              ? "Listening…"
              : "Ready"}
          </span>

          {/* Separator */}
          <div style={{ width: 1, height: 24, background: "rgba(255,255,255,0.12)" }} />

          {/* Camera button */}
          <button
            onClick={isStreaming ? stopWebcam : startWebcam}
            style={
              {
                width: 44,
                height: 44,
                borderRadius: "50%",
                background: isStreaming ? "rgba(10,132,255,0.75)" : "rgba(255,255,255,0.10)",
                border: isStreaming
                  ? "1px solid rgba(10,132,255,0.5)"
                  : "1px solid rgba(255,255,255,0.14)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                cursor: "pointer",
                transition: "background 200ms, border 200ms, transform 150ms",
                boxShadow: isStreaming ? "0 0 18px rgba(10,132,255,0.35)" : "none",
              } as React.CSSProperties
            }
            onMouseEnter={(e) => {
              ;(e.currentTarget as HTMLButtonElement).style.transform = "scale(1.08)"
            }}
            onMouseLeave={(e) => {
              ;(e.currentTarget as HTMLButtonElement).style.transform = "scale(1)"
            }}
          >
            {isStreaming ? (
              <Video style={{ width: 18, height: 18, color: "#fff" }} />
            ) : (
              <VideoOff style={{ width: 18, height: 18, color: "rgba(255,255,255,0.75)" }} />
            )}
          </button>
          <span
            style={{
              fontSize: 11.5,
              fontWeight: 500,
              color: "rgba(255,255,255,0.55)",
              letterSpacing: "-0.1px",
              textShadow: "0 1px 3px rgba(0,0,0,0.8)",
              minWidth: 60,
            }}
          >
            {isStreaming ? "Camera On" : "Start"}
          </span>

          {/* Separator */}
          <div style={{ width: 1, height: 24, background: "rgba(255,255,255,0.12)" }} />

          {/* Ray-Ban Mode Toggle */}
          <button
            onClick={() => setIsRayBanMode((p) => !p)}
            disabled={!isStreaming}
            style={
              {
                padding: "9px 18px",
                borderRadius: 24,
                background: isRayBanMode ? "rgba(48,209,88,0.75)" : "rgba(255,255,255,0.10)",
                border: isRayBanMode
                  ? "1px solid rgba(48,209,88,0.5)"
                  : "1px solid rgba(255,255,255,0.14)",
                color: isRayBanMode ? "#fff" : "rgba(255,255,255,0.85)",
                fontSize: 12.5,
                fontWeight: 600,
                cursor: !isStreaming ? "not-allowed" : "pointer",
                opacity: !isStreaming ? 0.4 : 1,
                transition: "background 200ms, border 200ms, transform 150ms",
                letterSpacing: "-0.1px",
                boxShadow: isRayBanMode ? "0 0 18px rgba(48,209,88,0.35)" : "none",
              } as React.CSSProperties
            }
            onMouseEnter={(e) => {
              if (isStreaming) (e.currentTarget as HTMLButtonElement).style.transform = "scale(1.05)"
            }}
            onMouseLeave={(e) => {
              ;(e.currentTarget as HTMLButtonElement).style.transform = "scale(1)"
            }}
          >
            {isRayBanMode ? "👓 AR Glasses HUD" : "HUD Mode"}
          </button>
        </div>

        {/* ── Interactive Voice Calibration Overlay ── */}
        {isCalibrating && (
          <div
            style={
              {
                position: "absolute",
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                background: "rgba(0,0,0,0.65)",
                backdropFilter: "blur(12px)",
                WebkitBackdropFilter: "blur(12px)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                zIndex: 100,
              } as React.CSSProperties
            }
          >
            <div
              style={{
                width: 360,
                padding: "28px 24px",
                borderRadius: 20,
                background: "rgba(20,25,35,0.92)",
                border: "1px solid rgba(10,132,255,0.5)",
                boxShadow: "0 0 35px rgba(10,132,255,0.3)",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                textAlign: "center",
                gap: 14,
              }}
            >
              <div
                style={{
                  width: 64,
                  height: 64,
                  borderRadius: "50%",
                  background: "rgba(10,132,255,0.2)",
                  border: "2px solid #0a84ff",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  animation: "pulse 1.2s infinite",
                  boxShadow: "0 0 20px rgba(10,132,255,0.5)",
                }}
              >
                <Mic style={{ width: 32, height: 32, color: "#64b5f6" }} />
              </div>

              <div>
                <h3 style={{ margin: 0, fontSize: 17, fontWeight: 700, color: "#fff" }}>
                  Calibrating Voice for {calibratingPerson}
                </h3>
                <p style={{ margin: "6px 0 0", fontSize: 12.5, color: "rgba(255,255,255,0.7)", lineHeight: 1.4 }}>
                  Please speak a natural sentence into your microphone right now...
                </p>
              </div>

              <div
                style={{
                  fontSize: 28,
                  fontWeight: 800,
                  color: "#0a84ff",
                  fontVariantNumeric: "tabular-nums",
                  letterSpacing: "-1px",
                }}
              >
                {calibrationCountdown}s
              </div>
            </div>
          </div>
        )}

        {/* ── Distinct Conversation History Modal ── */}
        {activeConversationPerson && (
          <div
            style={
              {
                position: "absolute",
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                background: "rgba(0,0,0,0.60)",
                backdropFilter: "blur(10px)",
                WebkitBackdropFilter: "blur(10px)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                zIndex: 90,
              } as React.CSSProperties
            }
          >
            <div
              style={{
                width: 460,
                maxHeight: "75vh",
                borderRadius: 20,
                background: "rgba(20,25,35,0.95)",
                border: "1px solid rgba(255,255,255,0.16)",
                boxShadow: "0 20px 50px rgba(0,0,0,0.8)",
                display: "flex",
                flexDirection: "column",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  padding: "16px 20px",
                  borderBottom: "1px solid rgba(255,255,255,0.10)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                }}
              >
                <div>
                  <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "#fff" }}>
                    Conversations with {activeConversationPerson}
                  </h3>
                  <span style={{ fontSize: 11, color: "rgba(255,255,255,0.5)" }}>
                    Distinct conversation logs segregated by individual
                  </span>
                </div>
                <button
                  onClick={() => setActiveConversationPerson(null)}
                  style={{
                    background: "none",
                    border: "none",
                    color: "rgba(255,255,255,0.6)",
                    cursor: "pointer",
                    padding: 4,
                  }}
                >
                  <X style={{ width: 18, height: 18 }} />
                </button>
              </div>

              <div style={{ padding: "16px 20px", flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 10 }}>
                {isLoadingConversations ? (
                  <p style={{ fontSize: 12, color: "rgba(255,255,255,0.5)", textAlign: "center", margin: 20 }}>
                    Loading conversations…
                  </p>
                ) : personConversations.length > 0 ? (
                  personConversations.map((conv) => (
                    <div
                      key={conv.id}
                      style={{
                        padding: "10px 12px",
                        borderRadius: 12,
                        background: "rgba(255,255,255,0.04)",
                        border: "1px solid rgba(255,255,255,0.08)",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                        <span style={{ fontSize: 11, fontWeight: 600, color: "#64b5f6" }}>
                          {conv.speaker || conv.person_name}
                        </span>
                        <span style={{ fontSize: 10, color: "rgba(255,255,255,0.4)" }}>
                          {new Date(conv.timestamp).toLocaleTimeString()}
                        </span>
                      </div>
                      <p style={{ margin: 0, fontSize: 12.5, color: "#fff", lineHeight: 1.4 }}>
                        &ldquo;{conv.text}&rdquo;
                      </p>
                      {conv.summary && (
                        <div style={{ marginTop: 6, fontSize: 11, color: "#30d158", fontWeight: 500 }}>
                          Memory Summary: {conv.summary}
                        </div>
                      )}
                    </div>
                  ))
                ) : (
                  <p style={{ fontSize: 12, color: "rgba(255,255,255,0.4)", textAlign: "center", margin: 24, fontStyle: "italic" }}>
                    No recorded conversations yet with {activeConversationPerson}.
                  </p>
                )}
              </div>

              <div
                style={{
                  padding: "12px 20px",
                  borderTop: "1px solid rgba(255,255,255,0.10)",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <button
                  onClick={() => handleClearPersonConversations(activeConversationPerson)}
                  disabled={personConversations.length === 0}
                  style={{
                    background: "none",
                    border: "none",
                    color: personConversations.length === 0 ? "rgba(255,107,107,0.3)" : "rgba(255,107,107,0.8)",
                    fontSize: 11.5,
                    cursor: personConversations.length === 0 ? "not-allowed" : "pointer",
                    textDecoration: "underline",
                  }}
                >
                  Clear Conversations
                </button>
                <button
                  onClick={() => setActiveConversationPerson(null)}
                  style={{
                    padding: "6px 14px",
                    borderRadius: 10,
                    background: "rgba(255,255,255,0.10)",
                    border: "1px solid rgba(255,255,255,0.16)",
                    color: "#fff",
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
