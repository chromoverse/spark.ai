import { useState, useEffect, useRef, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { MessageSquareWarning, Mic, MicOff, Settings } from "lucide-react";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { setSelectedInputDeviceId } from "@/store/features/device/deviceSlice";
import { toggleMicrophoneListening } from "@/store/features/localState/localSlice";
import { useSocket } from "@/context/socketContextProvider";
import AudioLevelProgress from "./AudioLevelProgress";

// ─── VAD Thresholds (tightened to reduce room noise false positives) ──────────
const VAD_POSITIVE_SPEECH_THRESHOLD = 0.75; // was 0.6 — now requires confident speech
const VAD_NEGATIVE_SPEECH_THRESHOLD = 0.55; // was 0.45 — cuts off faster after silence
const VAD_MIN_SPEECH_MS = 500; // was 360 — ignores short noise bursts
const VAD_REDEMPTION_MS = 400; // was 800 — stops recording sooner
const VAD_PRE_SPEECH_PAD_MS = 120;

const PROCESSING_TIMEOUT_MS = 30_000;
const PCM_MIME_TYPE = "audio/pcm;rate=16000";
const MIN_PCM_SAMPLES = 1600; // ~100ms at 16kHz

const VAD_BASE_ASSET_PATH = import.meta.env.DEV
  ? "/node_modules/@ricky0123/vad-web/dist/"
  : "../node_modules/@ricky0123/vad-web/dist/";

const ORT_WASM_BASE_PATH = import.meta.env.DEV
  ? "/node_modules/onnxruntime-web/dist/"
  : "../node_modules/onnxruntime-web/dist/";

interface MicVadLike {
  start: () => void | Promise<void>;
  pause: () => void;
  destroy: () => void | Promise<void>;
}

interface VadModuleLike {
  MicVAD: {
    new: (options: Record<string, unknown>) => Promise<MicVadLike>;
  };
}

// ─── Module-level VAD cache — loaded ONCE, never re-imported ─────────────────
let cachedVadModule: VadModuleLike | null = null;
const getVadModule = async (): Promise<VadModuleLike> => {
  if (!cachedVadModule) {
    cachedVadModule =
      (await import("@ricky0123/vad-web")) as unknown as VadModuleLike;
  }
  return cachedVadModule;
};

const createSessionId = (): string => crypto.randomUUID();

const float32ToPCM16Buffer = (float32Array: Float32Array): ArrayBuffer => {
  const pcm = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    const clamped = Math.max(-1, Math.min(1, float32Array[i]));
    pcm[i] = clamped < 0 ? clamped * 32768 : clamped * 32767;
  }
  return pcm.buffer;
};

export function AudioInput({ isAiPanel }: { isAiPanel?: boolean }) {
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

  // Audio visualization refs
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animationRef = useRef<number | null>(null);

  // VAD refs
  const vadRef = useRef<MicVadLike | null>(null);
  const hasAutoStartedRef = useRef(false);
  const listenGenerationRef = useRef(0);

  // Processing refs
  const processingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const isProcessingRef = useRef(false);

  const getErrorMessage = useCallback((error: unknown): string => {
    if (error instanceof Error) return error.message;
    return String(error);
  }, []);

  const getErrorName = useCallback((error: unknown): string => {
    if (error instanceof Error) return error.name;
    return "";
  }, []);

  const buildAudioConstraints = useCallback(
    (useExact: boolean): MediaStreamConstraints => {
      const deviceId = selectedInputDeviceId || audioInputDevices[0]?.deviceId;
      if (!deviceId) {
        return {
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
          video: false,
        };
      }
      return {
        audio: useExact
          ? {
              deviceId: { exact: deviceId },
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
            }
          : {
              deviceId: { ideal: deviceId },
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
            },
        video: false,
      };
    },
    [audioInputDevices, selectedInputDeviceId],
  );

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
        if (!analyserRef.current) return;
        analyserRef.current.getByteFrequencyData(dataArray);
        const average = dataArray.reduce((a, b) => a + b) / dataArray.length;
        setAudioLevel(average);
        animationRef.current = requestAnimationFrame(tick);
      };
      tick();
    } catch (error) {
      console.error("Error setting up audio visualization:", error);
    }
  }, []);

  const clearProcessingState = useCallback(() => {
    if (processingTimeoutRef.current) {
      clearTimeout(processingTimeoutRef.current);
      processingTimeoutRef.current = null;
    }
    isProcessingRef.current = false;
    setIsProcessing(false);
  }, []);

  const finalizeSession = useCallback(
    (sessionId: string) => {
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
        clearProcessingState();
      }, PROCESSING_TIMEOUT_MS);
      emit("user-stop-speaking", { sessionId, timestamp: Date.now() });
      console.log(
        `📤 user-stop-speaking emitted — session: ${sessionId.slice(0, 8)}…`,
      );
    },
    [clearProcessingState, emit, isConnected, socket],
  );

  const handleSpeechEnd = useCallback(
    (audioFloat32Array: Float32Array) => {
      setIsSpeaking(false);
      setIsRecording(false);
      if (!socket || !isConnected) {
        console.warn("⚠️ Dropping speech clip: socket disconnected");
        return;
      }
      if (isProcessingRef.current) {
        console.log("⏸️ Processing in-flight, skipping new speech clip");
        return;
      }
      if (!audioFloat32Array || audioFloat32Array.length < MIN_PCM_SAMPLES) {
        console.log("⏭️ Speech clip too short, skipping");
        return;
      }
      const sessionId = createSessionId();
      const pcmBuffer = float32ToPCM16Buffer(audioFloat32Array);
      emit("user-speaking", {
        audio: pcmBuffer,
        mimeType: PCM_MIME_TYPE,
        sessionId,
        seq: 0,
        timestamp: Date.now(),
      });
      console.log(
        `📤 PCM clip sent (${pcmBuffer.byteLength} bytes) session: ${sessionId.slice(0, 8)}…`,
      );
      finalizeSession(sessionId);
    },
    [emit, finalizeSession, isConnected, socket],
  );

  const teardownAudioResources = useCallback(async () => {
    const vad = vadRef.current;
    vadRef.current = null;
    if (vad) {
      try {
        if (typeof vad.pause === "function") vad.pause();
        if (typeof vad.destroy === "function") await vad.destroy();
      } catch (error) {
        console.warn("⚠️ Failed to teardown VAD cleanly:", error);
      }
    }
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current);
      animationRef.current = null;
    }
    analyserRef.current = null;
    const audioContext = audioContextRef.current;
    audioContextRef.current = null;
    if (audioContext) {
      try {
        if (audioContext.state !== "closed") await audioContext.close();
      } catch (error) {
        const isInvalidStateError =
          (error instanceof DOMException &&
            error.name === "InvalidStateError") ||
          (error instanceof Error && error.name === "InvalidStateError");
        if (!isInvalidStateError) {
          console.warn("⚠️ Failed to close AudioContext cleanly:", error);
        }
      }
    }
    if (streamRef.current) {
      streamRef.current
        .getTracks()
        .forEach((track: MediaStreamTrack) => track.stop());
      streamRef.current = null;
    }
    setAudioLevel(0);
    setIsSpeaking(false);
    setIsRecording(false);
  }, []);

  const startListening = useCallback(async () => {
    // ✅ FIX: Guard against redundant restarts — if VAD is already running, skip
    if (vadRef.current) {
      console.log("⏸️ VAD already running, skipping redundant restart");
      return;
    }

    const generation = ++listenGenerationRef.current;

    try {
      await teardownAudioResources();
      await new Promise((resolve) => setTimeout(resolve, 100));

      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia(
          buildAudioConstraints(true),
        );
      } catch (exactError: unknown) {
        console.warn(
          "⚠️ Exact device failed, trying ideal:",
          getErrorMessage(exactError),
        );
        try {
          stream = await navigator.mediaDevices.getUserMedia(
            buildAudioConstraints(false),
          );
        } catch (idealError: unknown) {
          console.warn(
            "⚠️ Ideal device failed, trying any mic:",
            getErrorMessage(idealError),
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

      if (generation !== listenGenerationRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }

      streamRef.current = stream;
      setupAudioVisualization(stream);

      // ✅ FIX: Use cached module — never re-imports after first load
      const { MicVAD } = await getVadModule();

      const vad = await MicVAD.new({
        startOnLoad: false,
        positiveSpeechThreshold: VAD_POSITIVE_SPEECH_THRESHOLD,
        negativeSpeechThreshold: VAD_NEGATIVE_SPEECH_THRESHOLD,
        minSpeechMs: VAD_MIN_SPEECH_MS,
        redemptionMs: VAD_REDEMPTION_MS,
        preSpeechPadMs: VAD_PRE_SPEECH_PAD_MS,
        baseAssetPath: VAD_BASE_ASSET_PATH,
        onnxWASMBasePath: ORT_WASM_BASE_PATH,
        getStream: async () => stream,
        onSpeechStart: () => {
          if (isProcessingRef.current) return;
          setIsSpeaking(true);
          setIsRecording(true);
          console.log("🎤 Speech started");
        },
        onSpeechEnd: (audioFloat32Array: Float32Array) => {
          handleSpeechEnd(audioFloat32Array);
        },
      });

      if (generation !== listenGenerationRef.current) {
        if (typeof vad.pause === "function") vad.pause();
        if (typeof vad.destroy === "function") await vad.destroy();
        return;
      }

      vadRef.current = vad;
      vad.start();
      console.log("✅ Audio stream + Silero VAD started");
    } catch (error: unknown) {
      console.error("❌ Error starting audio/VAD:", error);
      const errorName = getErrorName(error);
      if (errorName === "NotReadableError")
        console.error("💡 Microphone may be in use by another app.");
      else if (errorName === "NotAllowedError")
        console.error("💡 Microphone permission was denied.");
      else if (errorName === "NotFoundError")
        console.error("💡 No microphone found.");
      if (isMicrophoneListening) dispatch(toggleMicrophoneListening());
    }
  }, [
    buildAudioConstraints,
    dispatch,
    getErrorMessage,
    getErrorName,
    handleSpeechEnd,
    isMicrophoneListening,
    setupAudioVisualization,
    teardownAudioResources,
  ]);

  const stopListening = useCallback(async () => {
    listenGenerationRef.current += 1;
    await teardownAudioResources();
    clearProcessingState();
  }, [clearProcessingState, teardownAudioResources]);

  // ─── Auto-start mic once devices + permissions are ready ─────────────────────
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
  }, [
    audioInputDevices.length,
    dispatch,
    hasPermissions,
    isMicrophoneListening,
  ]);

  // ✅ FIX: Single unified effect — was two separate effects causing double startListening
  // Also handles device changes (selectedInputDeviceId) by restarting the stream
  useEffect(() => {
    if (isMicrophoneListening) {
      // Force a fresh start when device changes by clearing the VAD guard
      vadRef.current = null;
      void startListening();
    } else {
      void stopListening();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMicrophoneListening, selectedInputDeviceId]);

  // ─── Cleanup on unmount ───────────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      void stopListening();
    };
  }, [stopListening]);

  // ─── Server response listeners ────────────────────────────────────────────────
  useEffect(() => {
    if (!socket || !isConnected) return;

    const resetProcessing = () => {
      clearProcessingState();
      console.log("✅ Processing complete, ready for next input");
    };

    const logLatencyMetrics = (payload: {
      requestId: string;
      success: boolean;
      sttReadyMs?: number | null;
      speechToFirstTtsMs?: number | null;
      firstLlmTokenMs?: number | null;
      firstTtsDispatchMs?: number | null;
      contextMs?: number | null;
      totalMs?: number | null;
      emittedChunks?: number;
      chars?: number;
      error?: string;
    }) => {
      console.log(
        "📊 Latency",
        JSON.stringify(
          {
            requestId: payload.requestId,
            success: payload.success,
            sttReadyMs: payload.sttReadyMs,
            speechToFirstTtsMs: payload.speechToFirstTtsMs,
            firstLlmTokenMs: payload.firstLlmTokenMs,
            firstTtsDispatchMs: payload.firstTtsDispatchMs,
            contextMs: payload.contextMs,
            totalMs: payload.totalMs,
            emittedChunks: payload.emittedChunks,
            chars: payload.chars,
            error: payload.error,
          },
          null,
          2,
        ),
      );
    };

    on("query-result", resetProcessing);
    on("ai-end", resetProcessing);
    on("query-error", resetProcessing);
    on("error", resetProcessing);
    on("latency-metrics", logLatencyMetrics);

    return () => {
      off("query-result", resetProcessing);
      off("ai-end", resetProcessing);
      off("query-error", resetProcessing);
      off("error", resetProcessing);
      off("latency-metrics", logLatencyMetrics);
    };
  }, [clearProcessingState, isConnected, off, on, socket]);

  // ─── UI handlers ──────────────────────────────────────────────────────────────
  const handleDeviceChange = (deviceId: string) => {
    dispatch(setSelectedInputDeviceId(deviceId));
  };

  const levelPercentage = Math.min((audioLevel / 128) * 100, 100);

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

  if (isAiPanel) {
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
            (audioLevel / 100) *
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
  }

  return (
    <div className="w-64 bg-gray-900 rounded-lg shadow-lg overflow-hidden">
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
          <div className="mt-2 pt-2 border-t border-gray-700 text-[10px] text-gray-500 space-y-0.5">
            <div>
              VAD speech threshold:{" "}
              <span className="text-gray-300">
                {VAD_POSITIVE_SPEECH_THRESHOLD}
              </span>
            </div>
            <div>
              VAD silence threshold:{" "}
              <span className="text-gray-300">
                {VAD_NEGATIVE_SPEECH_THRESHOLD}
              </span>
            </div>
            <div>
              PCM transport:{" "}
              <span className="text-gray-300">{PCM_MIME_TYPE}</span>
            </div>
          </div>
        </div>
      )}

      <div className="p-3 bg-gray-900">
        <div className="mb-1 flex justify-between items-center">
          <span className="text-xs text-gray-400">Audio Level</span>
          <span className="text-xs text-white font-mono">
            {Math.round(levelPercentage)}%
          </span>
        </div>
        <AudioLevelProgress level={audioLevel} />
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
