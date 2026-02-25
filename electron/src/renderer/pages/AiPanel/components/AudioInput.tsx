import { useState, useEffect, useRef, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { MessageSquareWarning, Mic, MicOff, Settings } from "lucide-react";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { setSelectedInputDeviceId } from "@/store/features/device/deviceSlice";
import { toggleMicrophoneListening } from "@/store/features/localState/localSlice";
import { useSocket } from "@/context/socketContextProvider";
// import AudioLevelProgress from "./AudioLevelProgress";

// ─── 🎛️ UNIVERSAL REACTIVITY CONTROL ─────────────────────────────────────────
//
//  Tweak ONE number (REACTIVITY) to control the whole component's sensitivity.
//
//  Range : 0.0 → 1.0
//    0.2  = very lazy  — only reacts to loud, sustained speech
//    0.5  = balanced   — good for quiet rooms (recommended default)
//    0.7  = sensitive  — picks up soft/distant voices easily
//    1.0  = hair-trigger — reacts to almost any sound
//
const REACTIVITY = 0.5;

// ── Derived thresholds (do NOT edit these manually — change REACTIVITY above) ──

/** Audio level (%) needed to start/confirm speaking */
const SPEAKING_THRESHOLD = 35 - REACTIVITY * 22; // 35 → 13

/** Audio level (%) considered absolute silence */
const SILENCE_THRESHOLD = 3 + REACTIVITY * 10; // 3  → 8

/** How many consecutive frames above threshold before we confirm speech */
const SPEAKING_CONFIRMATION_SAMPLES = Math.round(3 - REACTIVITY * 2); // 3 → 1

/** How long (ms) of continuous silence before we finalize the recording.
 *  Higher REACTIVITY = shorter patience = faster cutoff after speech ends.
 *  But we never cut below 1800 ms so real speech isn't chopped. */
const SILENCE_DURATION = Math.round(2500 - REACTIVITY * 1400); // 3200 → 1800

// ─── Other Constants (tune freely) ───────────────────────────────────────────

/**
 * Toggle between Groq mode (single full-session blob) and default mode
 * (chunked segment streaming). Flip this one flag to switch behavior.
 */
const USE_GROQ = true;

/** Interval between chunk captures (ms) */
const CHUNK_INTERVAL_MS = 2000;
/** Minimum recording length to avoid false triggers (ms) */
const MIN_RECORDING_DURATION_MS = 600;
/** Minimum chunk blob size worth sending (bytes) */
const MIN_CHUNK_SIZE_BYTES = 500;
/** Safety timeout if server never responds (ms) */
const PROCESSING_TIMEOUT_MS = 30_000;

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Convert a Blob to an ArrayBuffer for binary socket transport. */
const blobToArrayBuffer = (blob: Blob): Promise<ArrayBuffer> =>
  blob.arrayBuffer();

/** Generate a unique session ID. */
const createSessionId = (): string => crypto.randomUUID();

/** Pick the best supported MIME type for recording. */
const getRecordingMimeType = (): string => {
  if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus"))
    return "audio/webm;codecs=opus";
  if (MediaRecorder.isTypeSupported("audio/webm")) return "audio/webm";
  return "audio/ogg";
};

// ─── Component ────────────────────────────────────────────────────────────────

export function AudioInput() {
  const dispatch = useAppDispatch();
  const { socket, isConnected, emit, on, off } = useSocket();

  // Redux state
  const audioInputDevices = useAppSelector(
    (state) => state.device.audioInputDevices,
  );
  const selectedInputDeviceId = useAppSelector(
    (state) => state.device.selectedInputDeviceId,
  );
  const hasPermissions = useAppSelector((state) => state.device.hasPermissions);
  const isMicrophoneListening = useAppSelector(
    (state) => state.localState.isMicrophoneListening,
  );

  // UI state
  const [inputAudioLevel, setInputAudioLevel] = useState(0);
  const [showSettings, setShowSettings] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);

  // Audio pipeline refs
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animationRef = useRef<number | null>(null);
  const hasAutoStartedRef = useRef(false);

  // Recording / streaming refs
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunkTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const silenceTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const processingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const isSpeakingRef = useRef(false);
  const isProcessingRef = useRef(false);
  const isRecordingRef = useRef(false);
  const recordingStartTimeRef = useRef(0);
  const speakingSamplesRef = useRef(0);

  // ── Streaming session refs ────────────────────────────────────────────
  const sessionIdRef = useRef<string | null>(null);
  const seqRef = useRef(0);
  const mimeTypeRef = useRef<string>("audio/webm;codecs=opus");
  /** Accumulated chunks for the current micro-recorder segment (default mode) */
  const segmentChunksRef = useRef<Blob[]>([]);
  /** Accumulated chunks for the entire speaking session (Groq mode) */
  const fullSessionChunksRef = useRef<Blob[]>([]);

  // ── Auto-start listening ──────────────────────────────────────────────

  useEffect(() => {
    if (
      hasPermissions &&
      audioInputDevices.length > 0 &&
      !isMicrophoneListening &&
      !hasAutoStartedRef.current
    ) {
      hasAutoStartedRef.current = true;
      dispatch(toggleMicrophoneListening());
    }
  }, [hasPermissions, audioInputDevices, dispatch]);

  useEffect(() => {
    if (isMicrophoneListening) {
      startListening();
    } else {
      stopListening();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMicrophoneListening]);

  useEffect(() => {
    if (isMicrophoneListening && selectedInputDeviceId) {
      startListening();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedInputDeviceId]);

  // ── Audio visualization + VAD ─────────────────────────────────────────

  const setupAudioVisualization = useCallback((stream: MediaStream) => {
    try {
      const audioContext = new AudioContext();
      const analyser = audioContext.createAnalyser();
      const microphone = audioContext.createMediaStreamSource(stream);

      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.8;
      microphone.connect(analyser);

      audioContextRef.current = audioContext;
      analyserRef.current = analyser;

      const dataArray = new Uint8Array(analyser.frequencyBinCount);

      const tick = () => {
        if (analyserRef.current) {
          analyserRef.current.getByteFrequencyData(dataArray);
          const average = dataArray.reduce((a, b) => a + b) / dataArray.length;
          setInputAudioLevel(average);
          handleVoiceActivity(average);
          animationRef.current = requestAnimationFrame(tick);
        }
      };

      tick();
    } catch (error) {
      console.error("Error setting up audio visualization:", error);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Voice Activity Detection ──────────────────────────────────────────

  const handleVoiceActivity = (level: number) => {
    const pct = (level / 128) * 100;

    // While waiting for server response, freeze VAD entirely
    if (isProcessingRef.current) {
      speakingSamplesRef.current = 0;
      return;
    }

    if (pct > SPEAKING_THRESHOLD) {
      // ── User is clearly speaking ──────────────────────────────────
      speakingSamplesRef.current++;

      if (
        speakingSamplesRef.current >= SPEAKING_CONFIRMATION_SAMPLES &&
        !isSpeakingRef.current
      ) {
        // Confirmed: speech has started
        isSpeakingRef.current = true;
        setIsSpeaking(true);
      }

      if (isSpeakingRef.current) {
        // CRITICAL: Every active speech frame resets the silence countdown.
        // This is what prevents mid-speech cutoffs.
        if (silenceTimeoutRef.current) {
          clearTimeout(silenceTimeoutRef.current);
          silenceTimeoutRef.current = null;
        }

        // Kick off recording if not already running
        if (!isRecordingRef.current) {
          startRecording();
        }

        // Arm the silence timer — it will fire only if no speech comes
        silenceTimeoutRef.current = setTimeout(
          handleSilenceDetected,
          SILENCE_DURATION,
        );
      }
    } else {
      // ── Below speaking threshold ──────────────────────────────────
      speakingSamplesRef.current = 0;

      if (isSpeakingRef.current) {
        if (pct <= SILENCE_THRESHOLD) {
          // True silence: start the countdown only if not already running
          if (!silenceTimeoutRef.current) {
            silenceTimeoutRef.current = setTimeout(
              handleSilenceDetected,
              SILENCE_DURATION,
            );
          }
        } else {
          // Dead zone (between SILENCE_THRESHOLD and SPEAKING_THRESHOLD).
          // This happens constantly during natural speech — between syllables,
          // breaths, pauses. We treat it like a speech continuation: reset
          // the silence clock so the recording is NEVER cut mid-sentence.
          if (silenceTimeoutRef.current) {
            clearTimeout(silenceTimeoutRef.current);
            silenceTimeoutRef.current = null;
          }
          silenceTimeoutRef.current = setTimeout(
            handleSilenceDetected,
            SILENCE_DURATION,
          );
        }
      }
    }
  };

  const handleSilenceDetected = () => {
    isSpeakingRef.current = false;
    setIsSpeaking(false);
    speakingSamplesRef.current = 0;

    if (silenceTimeoutRef.current) {
      clearTimeout(silenceTimeoutRef.current);
      silenceTimeoutRef.current = null;
    }

    if (isRecordingRef.current) {
      stopRecording();
    }
  };

  // ── Recording lifecycle ───────────────────────────────────────────────

  const startRecording = () => {
    if (
      !streamRef.current ||
      isRecordingRef.current ||
      isProcessingRef.current
    ) {
      return;
    }

    const mimeType = getRecordingMimeType();
    mimeTypeRef.current = mimeType;

    const sessionId = createSessionId();
    sessionIdRef.current = sessionId;
    seqRef.current = 0;

    isRecordingRef.current = true;
    setIsRecording(true);
    recordingStartTimeRef.current = Date.now();

    console.log(
      `🎙️ Recording started (${USE_GROQ ? "GROQ" : "DEFAULT"} mode) — session: ${sessionId.slice(0, 8)}… | REACTIVITY=${REACTIVITY} | THRESHOLD=${SPEAKING_THRESHOLD.toFixed(1)}% | SILENCE=${SILENCE_DURATION}ms`,
    );

    if (USE_GROQ) {
      fullSessionChunksRef.current = [];

      try {
        const recorder = new MediaRecorder(streamRef.current, {
          mimeType: mimeTypeRef.current,
          audioBitsPerSecond: 128000,
        });

        recorder.ondataavailable = (event: BlobEvent) => {
          if (event.data.size > 0) {
            fullSessionChunksRef.current.push(event.data);
          }
        };

        recorder.onstop = async () => {
          const blob = new Blob(fullSessionChunksRef.current, {
            type: mimeTypeRef.current,
          });
          fullSessionChunksRef.current = [];

          const duration = Date.now() - recordingStartTimeRef.current;
          if (duration < MIN_RECORDING_DURATION_MS) {
            console.log("⏭️ Recording too short, discarding session");
            sessionIdRef.current = null;
            seqRef.current = 0;
            mediaRecorderRef.current = null;
            return;
          }

          if (blob.size >= MIN_CHUNK_SIZE_BYTES && sessionIdRef.current) {
            try {
              const buffer = await blobToArrayBuffer(blob);
              emit("user-speaking", {
                audio: buffer,
                mimeType: mimeTypeRef.current,
                sessionId: sessionIdRef.current,
                seq: 0,
                timestamp: Date.now(),
              });
              console.log(
                `📤 Full session blob sent (${blob.size} bytes) session: ${sessionIdRef.current.slice(0, 8)}…`,
              );
              finalizeSession(sessionIdRef.current);
            } catch (err) {
              console.error("❌ Error sending full session blob:", err);
            }
          }

          sessionIdRef.current = null;
          seqRef.current = 0;
          mediaRecorderRef.current = null;
        };

        recorder.onerror = (event: Event) => {
          console.error("❌ MediaRecorder (Groq) error:", event);
        };

        recorder.start(250);
        mediaRecorderRef.current = recorder;
      } catch (error) {
        console.error("❌ Error starting Groq recorder:", error);
      }
    } else {
      startSegmentRecorder();
    }
  };

  const startSegmentRecorder = () => {
    if (!streamRef.current || !isRecordingRef.current) return;

    try {
      segmentChunksRef.current = [];

      const recorder = new MediaRecorder(streamRef.current, {
        mimeType: mimeTypeRef.current,
        audioBitsPerSecond: 128000,
      });

      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data.size > 0) {
          segmentChunksRef.current.push(event.data);
        }
      };

      recorder.onstop = async () => {
        const blob = new Blob(segmentChunksRef.current, {
          type: mimeTypeRef.current,
        });
        segmentChunksRef.current = [];

        if (blob.size >= MIN_CHUNK_SIZE_BYTES && sessionIdRef.current) {
          try {
            const buffer = await blobToArrayBuffer(blob);
            const seq = seqRef.current++;

            emit("user-speaking", {
              audio: buffer,
              mimeType: mimeTypeRef.current,
              sessionId: sessionIdRef.current,
              seq,
              timestamp: Date.now(),
            });

            console.log(
              `📤 Chunk #${seq} sent (${blob.size} bytes) session: ${sessionIdRef.current.slice(0, 8)}…`,
            );
          } catch (err) {
            console.error("❌ Error sending audio chunk:", err);
          }
        }

        if (isRecordingRef.current) {
          startSegmentRecorder();
        } else {
          handleRecordingFinished();
        }
      };

      recorder.onerror = (event: Event) => {
        console.error("❌ MediaRecorder segment error:", event);
        if (isRecordingRef.current) {
          startSegmentRecorder();
        }
      };

      recorder.start();
      mediaRecorderRef.current = recorder;

      chunkTimerRef.current = setTimeout(() => {
        if (recorder.state === "recording" || recorder.state === "paused") {
          recorder.stop();
        }
      }, CHUNK_INTERVAL_MS);
    } catch (error) {
      console.error("❌ Error starting segment recorder:", error);
    }
  };

  const stopRecording = () => {
    if (!isRecordingRef.current) return;

    isRecordingRef.current = false;
    setIsRecording(false);

    if (USE_GROQ) {
      const recorder = mediaRecorderRef.current;
      if (
        recorder &&
        (recorder.state === "recording" || recorder.state === "paused")
      ) {
        recorder.stop();
        console.log("⏹️ Recording stopped (Groq mode)");
      }
    } else {
      if (chunkTimerRef.current) {
        clearTimeout(chunkTimerRef.current);
        chunkTimerRef.current = null;
      }

      const recorder = mediaRecorderRef.current;
      if (
        recorder &&
        (recorder.state === "recording" || recorder.state === "paused")
      ) {
        recorder.stop();
        console.log("⏹️ Recording stopped (default mode)");
      } else {
        handleRecordingFinished();
      }
    }
  };

  const handleRecordingFinished = () => {
    const duration = Date.now() - recordingStartTimeRef.current;

    if (duration < MIN_RECORDING_DURATION_MS) {
      console.log("⏭️ Recording too short, discarding session");
      sessionIdRef.current = null;
      seqRef.current = 0;
      mediaRecorderRef.current = null;
      return;
    }

    if (sessionIdRef.current && seqRef.current > 0) {
      finalizeSession(sessionIdRef.current);
    }

    sessionIdRef.current = null;
    seqRef.current = 0;
    mediaRecorderRef.current = null;
  };

  // ── Finalize session ──────────────────────────────────────────────────

  const finalizeSession = (sessionId: string) => {
    if (!socket || !isConnected) {
      console.error("❌ Socket not connected, cannot finalize session");
      return;
    }

    if (isProcessingRef.current) {
      console.log("⏸️ Already processing, skipping finalize");
      return;
    }

    isProcessingRef.current = true;
    setIsProcessing(true);

    processingTimeoutRef.current = setTimeout(() => {
      console.warn("⏰ Processing timeout — resetting state");
      isProcessingRef.current = false;
      setIsProcessing(false);
    }, PROCESSING_TIMEOUT_MS);

    emit("user-stop-speaking", {
      sessionId,
      timestamp: Date.now(),
    });

    console.log(
      `📤 user-stop-speaking emitted — session: ${sessionId.slice(0, 8)}…`,
    );
  };

  // ── Server response listeners ─────────────────────────────────────────

  useEffect(() => {
    if (socket && isConnected) {
      const resetProcessing = () => {
        if (processingTimeoutRef.current) {
          clearTimeout(processingTimeoutRef.current);
          processingTimeoutRef.current = null;
        }
        isProcessingRef.current = false;
        setIsProcessing(false);
        console.log("✅ Processing complete, ready for next input");
      };

      on("query-result", resetProcessing);
      on("tts-end", resetProcessing);
      on("query-error", resetProcessing);
      on("error", resetProcessing);

      return () => {
        off("query-result", resetProcessing);
        off("tts-end", resetProcessing);
        off("query-error", resetProcessing);
        off("error", resetProcessing);
      };
    }
  }, [socket, isConnected, on, off]);

  // ── Microphone stream management ──────────────────────────────────────

  const startListening = async () => {
    try {
      if (streamRef.current) {
        streamRef.current
          .getTracks()
          .forEach((track: MediaStreamTrack) => track.stop());
        streamRef.current = null;
      }
      if (audioContextRef.current) {
        await audioContextRef.current.close();
        audioContextRef.current = null;
      }
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
        animationRef.current = null;
      }

      await new Promise((resolve) => setTimeout(resolve, 100));

      const deviceId = selectedInputDeviceId || audioInputDevices[0]?.deviceId;

      const getConstraints = (useExact: boolean): MediaStreamConstraints => ({
        audio:
          deviceId && useExact
            ? {
                deviceId: { exact: deviceId },
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
              }
            : deviceId && !useExact
              ? {
                  deviceId: { ideal: deviceId },
                  echoCancellation: true,
                  noiseSuppression: true,
                  autoGainControl: true,
                }
              : {
                  echoCancellation: true,
                  noiseSuppression: true,
                  autoGainControl: true,
                },
        video: false,
      });

      let stream: MediaStream | null = null;

      try {
        stream = await navigator.mediaDevices.getUserMedia(
          getConstraints(true),
        );
      } catch (exactError: any) {
        console.warn(
          "⚠️ Exact device failed, trying ideal:",
          exactError.message,
        );
        try {
          stream = await navigator.mediaDevices.getUserMedia(
            getConstraints(false),
          );
        } catch (idealError: any) {
          console.warn(
            "⚠️ Ideal device failed, trying any mic:",
            idealError.message,
          );
          stream = await navigator.mediaDevices.getUserMedia({
            audio: {
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
            },
            video: false,
          });
        }
      }

      if (stream) {
        streamRef.current = stream;
        setupAudioVisualization(stream);
        console.log("✅ Audio stream started successfully");
      }
    } catch (error: any) {
      console.error("❌ Error starting audio:", error);

      if (error.name === "NotReadableError") {
        console.error("💡 Microphone may be in use by another app.");
      } else if (error.name === "NotAllowedError") {
        console.error("💡 Microphone permission was denied.");
      } else if (error.name === "NotFoundError") {
        console.error("💡 No microphone found.");
      }

      if (isMicrophoneListening) {
        dispatch(toggleMicrophoneListening());
      }
    }
  };

  const stopListening = async () => {
    if (isRecordingRef.current) {
      stopRecording();
      await new Promise((resolve) => setTimeout(resolve, 300));
    }

    if (chunkTimerRef.current) {
      clearTimeout(chunkTimerRef.current);
      chunkTimerRef.current = null;
    }
    if (silenceTimeoutRef.current) {
      clearTimeout(silenceTimeoutRef.current);
      silenceTimeoutRef.current = null;
    }
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current);
      animationRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }

    analyserRef.current = null;
    setInputAudioLevel(0);
    isRecordingRef.current = false;
    setIsRecording(false);
    setIsSpeaking(false);
    isSpeakingRef.current = false;
    speakingSamplesRef.current = 0;

    if (streamRef.current) {
      streamRef.current
        .getTracks()
        .forEach((track: MediaStreamTrack) => track.stop());
      streamRef.current = null;
    }
  };

  useEffect(() => {
    return () => {
      stopListening();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── UI handlers ───────────────────────────────────────────────────────

  const handleDeviceChange = (deviceId: string) => {
    dispatch(setSelectedInputDeviceId(deviceId));
  };

  const levelPercentage = Math.min((inputAudioLevel / 128) * 100, 100);

  // ── Render ────────────────────────────────────────────────────────────

  if (!hasPermissions) {
    return (
      <div className="w-64 bg-gray-800 rounded-lg shadow-lg p-4">
        <div className="text-center text-white">
          <p className="text-sm mb-2">Microphone access needed</p>
          <Button
            onClick={() => {}}
            size="sm"
            className="bg-blue-600 hover:bg-blue-700"
          >
            Grant Permission
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex items-center gap-0.5 h-7">
      {!isMicrophoneListening && (
        <div 
          className="absolute -top-1 -right-2 w-2 h-2 rounded-full bg-red-500 shadow-[0_0_4px_rgba(239,68,68,0.8)] z-10" 
          title="Microphone Muted" 
        />
      )}
      {isProcessing && (
        <div 
          className="absolute -top-1 -right-2 w-2 h-2 rounded-full border-[1.5px] border-blue-400 border-t-transparent animate-spin z-10" 
          title="Processing Query" 
        />
      )}
      {Array.from({ length: 4 }).map((_, i) => {
        const height = Math.max(
          20,
          (inputAudioLevel / 100) *
            100 *
            (0.5 + Math.sin(Date.now() / 200 + i) * 0.5),
        );
        return (
          <div
            key={i}
            className="w-[3px] rounded-sm bg-linear-to-t from-indigo-500 to-indigo-300 transition-[height] duration-75 ease-out"
            style={{ height: `${height}%` }}
          />
        );
      })}
    </div>
  );

  // return (
  //   <div className="w-64 bg-gray-900 rounded-lg shadow-lg overflow-hidden">
  //     {/* Header */}
  //     <div className="flex items-center justify-between p-2 bg-gray-800">
  //       <div className="flex items-center gap-2">
  //         {isMicrophoneListening ? (
  //           <Mic className="w-4 h-4 text-green-500" />
  //         ) : (
  //           <MicOff className="w-4 h-4 text-gray-400" />
  //         )}
  //         <span className="text-white text-sm font-medium">Microphone</span>
  //         {isRecording && (
  //           <span className="flex items-center gap-1 text-xs text-red-500 animate-pulse">
  //             <span className="w-2 h-2 bg-red-500 rounded-full"></span>
  //             REC
  //           </span>
  //         )}
  //         {isProcessing && (
  //           <span className="flex items-center gap-1 text-xs text-blue-500 animate-pulse">
  //             <span className="w-2 h-2 bg-blue-500 rounded-full"></span>
  //             WAIT
  //           </span>
  //         )}
  //       </div>
  //       <Button
  //         onClick={() => setShowSettings(!showSettings)}
  //         variant="ghost"
  //         size="sm"
  //         className="h-7 w-7 p-0 text-gray-300 hover:text-white hover:bg-gray-700"
  //       >
  //         <Settings className="w-4 h-4" />
  //       </Button>
  //     </div>

  //     {/* Settings Panel */}
  //     {showSettings && (
  //       <div className="p-3 bg-gray-800 border-t border-gray-700">
  //         <label className="block text-xs text-gray-300 mb-2">
  //           Select Microphone
  //         </label>
  //         <select
  //           value={
  //             selectedInputDeviceId || audioInputDevices[0]?.deviceId || ""
  //           }
  //           onChange={(e) => handleDeviceChange(e.target.value)}
  //           className="w-full px-2 py-1 text-sm bg-gray-700 border border-gray-600 rounded text-white focus:ring-2 focus:ring-blue-500 focus:outline-none"
  //         >
  //           {audioInputDevices.map((device) => (
  //             <option key={device.deviceId} value={device.deviceId}>
  //               {device.label || `Microphone ${device.deviceId.slice(0, 8)}`}
  //             </option>
  //           ))}
  //         </select>
  //         {/* Reactivity debug info */}
  //         <div className="mt-2 pt-2 border-t border-gray-700 text-[10px] text-gray-500 space-y-0.5">
  //           <div>
  //             Reactivity: <span className="text-gray-300">{REACTIVITY}</span>
  //           </div>
  //           <div>
  //             Speech threshold:{" "}
  //             <span className="text-gray-300">
  //               {SPEAKING_THRESHOLD.toFixed(1)}%
  //             </span>
  //           </div>
  //           <div>
  //             Silence threshold:{" "}
  //             <span className="text-gray-300">
  //               {SILENCE_THRESHOLD.toFixed(1)}%
  //             </span>
  //           </div>
  //           <div>
  //             Silence timeout:{" "}
  //             <span className="text-gray-300">{SILENCE_DURATION}ms</span>
  //           </div>
  //         </div>
  //       </div>
  //     )}

  //     {/* Audio Level Indicator */}
  //     <div className="p-3 bg-gray-900">
  //       <div className="mb-1 flex justify-between items-center">
  //         <span className="text-xs text-gray-400">Audio Level</span>
  //         <span className="text-xs text-white font-mono">
  //           {Math.round(levelPercentage)}%
  //         </span>
  //       </div>
  //       {/* <AudioLevelProgress level={inputAudioLevel} /> */}

  //       {/* Status indicators */}
  //       <div className="mt-2 space-y-1">
  //         {!isMicrophoneListening && (
  //           <span className="text-[12px] text-red-400 flex gap-1 items-center">
  //             <MessageSquareWarning size={10} /> Microphone is muted
  //           </span>
  //         )}
  //         {isSpeaking && !isProcessing && (
  //           <span className="text-[12px] text-green-400 flex gap-1 items-center">
  //             <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse"></span>
  //             Speaking detected
  //           </span>
  //         )}
  //         {isProcessing && (
  //           <span className="text-[12px] text-blue-400 flex gap-1 items-center">
  //             <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse"></span>
  //             Processing request...
  //           </span>
  //         )}
  //         {!isConnected && (
  //           <span className="text-[12px] text-yellow-400 flex gap-1 items-center">
  //             <MessageSquareWarning size={10} /> Socket disconnected
  //           </span>
  //         )}
  //       </div>
  //     </div>
  //   </div>
  // );
}

export default AudioInput;
