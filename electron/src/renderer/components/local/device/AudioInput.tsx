import { useState, useEffect, useRef, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { MessageSquareWarning, Mic, MicOff, Settings } from "lucide-react";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { setSelectedInputDeviceId } from "@/store/features/device/deviceSlice";
import { toggleMicrophoneListening } from "@/store/features/localState/localSlice";
import { useSocket } from "@/context/socketContextProvider";
import AudioLevelProgress from "./AudioLevelProgress";

// ─── Constants ────────────────────────────────────────────────────────────────

/** Minimum audio level (%) to count as a "speaking" sample */
const SPEAKING_THRESHOLD = 55;
/** Audio level (%) below which we consider it absolute silence */
const SILENCE_THRESHOLD = 20;
/** How long silence must persist before we finalize (ms) */
const SILENCE_DURATION = 2000;
/** Consecutive frames above SPEAKING_THRESHOLD to confirm speech */
const SPEAKING_CONFIRMATION_SAMPLES = 2;
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
  const [audioLevel, setAudioLevel] = useState(0);
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
  /** Accumulated chunks for the current micro-recorder segment */
  const segmentChunksRef = useRef<Blob[]>([]);

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
          const average =
            dataArray.reduce((a, b) => a + b) / dataArray.length;
          setAudioLevel(average);
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

    if (isProcessingRef.current) {
      speakingSamplesRef.current = 0;
      return;
    }

    if (pct > SPEAKING_THRESHOLD) {
      speakingSamplesRef.current++;

      if (
        speakingSamplesRef.current >= SPEAKING_CONFIRMATION_SAMPLES &&
        !isSpeakingRef.current
      ) {
        isSpeakingRef.current = true;
        setIsSpeaking(true);

        if (silenceTimeoutRef.current) {
          clearTimeout(silenceTimeoutRef.current);
          silenceTimeoutRef.current = null;
        }

        if (!isRecordingRef.current) {
          startRecording();
        }
      }

      if (isSpeakingRef.current) {
        if (silenceTimeoutRef.current) {
          clearTimeout(silenceTimeoutRef.current);
        }
        silenceTimeoutRef.current = setTimeout(
          handleSilenceDetected,
          SILENCE_DURATION,
        );
      }
    } else {
      speakingSamplesRef.current = 0;

      if (pct <= SILENCE_THRESHOLD && isSpeakingRef.current) {
        if (!silenceTimeoutRef.current) {
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

    // Signal that the overall recording should end.
    // stopRecording will stop the current micro-recorder and finalize.
    if (isRecordingRef.current) {
      stopRecording();
    }
  };

  // ── Recording lifecycle (stop-restart approach) ───────────────────────
  //
  // Instead of using MediaRecorder.start(timeslice)  — which produces
  // WebM *fragments* that can't be decoded individually — we create a
  // fresh MediaRecorder for each ~2 s segment, stop it to get a complete
  // self-contained audio blob, send it, then start a new one.
  //
  // The MediaStream stays alive throughout; only the recorder rotates.

  /** Start a brand-new recording session. */
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

    // Fresh session
    const sessionId = createSessionId();
    sessionIdRef.current = sessionId;
    seqRef.current = 0;

    isRecordingRef.current = true;
    setIsRecording(true);
    recordingStartTimeRef.current = Date.now();

    console.log(
      `🎙️ Recording started — session: ${sessionId.slice(0, 8)}…`,
    );

    // Kick off the first micro-recorder segment
    startSegmentRecorder();
  };

  /** Create a micro-recorder that captures one ~2 s segment. */
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
        // Build a complete, self-contained audio blob from the segment
        const blob = new Blob(segmentChunksRef.current, {
          type: mimeTypeRef.current,
        });
        segmentChunksRef.current = [];

        if (blob.size >= MIN_CHUNK_SIZE_BYTES && sessionIdRef.current) {
          try {
            // Send raw binary — no base64 overhead (~33% smaller, no encode/decode CPU cost)
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
              `📤 Chunk #${seq} sent (${blob.size} bytes, binary) ` +
                `session: ${sessionIdRef.current.slice(0, 8)}…`,
            );
          } catch (err) {
            console.error("❌ Error sending audio chunk:", err);
          }
        }

        // If still recording, start the next segment. Otherwise finalize.
        if (isRecordingRef.current) {
          startSegmentRecorder();
        } else {
          handleRecordingFinished();
        }
      };

      recorder.onerror = (event: Event) => {
        console.error("❌ MediaRecorder segment error:", event);
        // Try to continue with a new segment
        if (isRecordingRef.current) {
          startSegmentRecorder();
        }
      };

      recorder.start(); // no timeslice — we'll stop it ourselves
      mediaRecorderRef.current = recorder;

      // Schedule a stop after CHUNK_INTERVAL_MS
      chunkTimerRef.current = setTimeout(() => {
        if (
          recorder.state === "recording" ||
          recorder.state === "paused"
        ) {
          recorder.stop();
        }
      }, CHUNK_INTERVAL_MS);
    } catch (error) {
      console.error("❌ Error starting segment recorder:", error);
    }
  };

  /** Stop the current recording session. */
  const stopRecording = () => {
    if (!isRecordingRef.current) return;

    // Mark as no longer recording so the onstop callback won't start
    // another segment and will instead call handleRecordingFinished().
    isRecordingRef.current = false;
    setIsRecording(false);

    // Clear the chunk timer
    if (chunkTimerRef.current) {
      clearTimeout(chunkTimerRef.current);
      chunkTimerRef.current = null;
    }

    // Stop the current micro-recorder (triggers onstop → send + finalize)
    const recorder = mediaRecorderRef.current;
    if (
      recorder &&
      (recorder.state === "recording" || recorder.state === "paused")
    ) {
      recorder.stop();
      console.log("⏹️ Recording stopped");
    } else {
      // Recorder already inactive — finalize directly
      handleRecordingFinished();
    }
  };

  /** Called after the final segment's onstop fires. */
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

  // ── Finalize session — tell server we're done speaking ────────────────

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

  // ── Listen for server response to reset processing lock ───────────────

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
    setAudioLevel(0);
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

  const levelPercentage = Math.min((audioLevel / 128) * 100, 100);

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
    <div className="w-64 bg-gray-900 rounded-lg shadow-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between p-2 bg-gray-800">
        <div className="flex items-center gap-2">
          {isMicrophoneListening ? (
            <Mic className="w-4 h-4 text-green-500" />
          ) : (
            <MicOff className="w-4 h-4 text-gray-400" />
          )}
          <span className="text-white text-sm font-medium">Microphone</span>
          {isRecording && (
            <span className="flex items-center gap-1 text-xs text-red-500 animate-pulse">
              <span className="w-2 h-2 bg-red-500 rounded-full"></span>
              REC
            </span>
          )}
          {isProcessing && (
            <span className="flex items-center gap-1 text-xs text-blue-500 animate-pulse">
              <span className="w-2 h-2 bg-blue-500 rounded-full"></span>
              WAIT
            </span>
          )}
        </div>
        <Button
          onClick={() => setShowSettings(!showSettings)}
          variant="ghost"
          size="sm"
          className="h-7 w-7 p-0 text-gray-300 hover:text-white hover:bg-gray-700"
        >
          <Settings className="w-4 h-4" />
        </Button>
      </div>

      {/* Settings Panel */}
      {showSettings && (
        <div className="p-3 bg-gray-800 border-t border-gray-700">
          <label className="block text-xs text-gray-300 mb-2">
            Select Microphone
          </label>
          <select
            value={
              selectedInputDeviceId || audioInputDevices[0]?.deviceId || ""
            }
            onChange={(e) => handleDeviceChange(e.target.value)}
            className="w-full px-2 py-1 text-sm bg-gray-700 border border-gray-600 rounded text-white focus:ring-2 focus:ring-blue-500 focus:outline-none"
          >
            {audioInputDevices.map((device) => (
              <option key={device.deviceId} value={device.deviceId}>
                {device.label || `Microphone ${device.deviceId.slice(0, 8)}`}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Audio Level Indicator */}
      <div className="p-3 bg-gray-900">
        <div className="mb-1 flex justify-between items-center">
          <span className="text-xs text-gray-400">Audio Level</span>
          <span className="text-xs text-white font-mono">
            {Math.round(levelPercentage)}%
          </span>
        </div>
        <AudioLevelProgress level={audioLevel} />

        {/* Status indicators */}
        <div className="mt-2 space-y-1">
          {!isMicrophoneListening && (
            <span className="text-[12px] text-red-400 flex gap-1 items-center">
              <MessageSquareWarning size={10} /> Microphone is muted
            </span>
          )}
          {isSpeaking && !isProcessing && (
            <span className="text-[12px] text-green-400 flex gap-1 items-center">
              <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse"></span>
              Speaking detected
            </span>
          )}
          {isProcessing && (
            <span className="text-[12px] text-blue-400 flex gap-1 items-center">
              <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse"></span>
              Processing request...
            </span>
          )}
          {!isConnected && (
            <span className="text-[12px] text-yellow-400 flex gap-1 items-center">
              <MessageSquareWarning size={10} /> Socket disconnected
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export default AudioInput;
