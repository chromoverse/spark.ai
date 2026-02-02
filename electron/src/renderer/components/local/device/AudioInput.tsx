import { useState, useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { MessageSquareWarning, Mic, MicOff, Settings } from "lucide-react";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { setSelectedInputDeviceId } from "@/store/features/device/deviceSlice";
import { toggleMicrophoneListening } from "@/store/features/localState/localSlice";
import { useSocket } from "@/context/socketContextProvider";
import AudioLevelProgress from "./AudioLevelProgress";

export function AudioInput() {
  const dispatch = useAppDispatch();
  const { socket, isConnected, emit, on, off } = useSocket();

  // Get state from Redux
  const audioInputDevices = useAppSelector(
    (state) => state.device.audioInputDevices
  );
  const selectedInputDeviceId = useAppSelector(
    (state) => state.device.selectedInputDeviceId
  );
  const hasPermissions = useAppSelector((state) => state.device.hasPermissions);
  const isMicrophoneListening = useAppSelector(
    (state) => state.localState.isMicrophoneListening
  );

  const [audioLevel, setAudioLevel] = useState(0);
  const [showSettings, setShowSettings] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [recordingStartTime, setRecordingStartTime] = useState<number>(0);

  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animationRef = useRef<number | null>(null);
  const hasAutoStartedRef = useRef(false);

  // Recording refs
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const silenceTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isSpeakingRef = useRef(false);
  const isProcessingRef = useRef(false);
  const isRecordingRef = useRef(false);
  const processingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null
  );

  // Voice Activity Detection settings
  const SILENCE_THRESHOLD = 15;
  const SILENCE_DURATION = 1500;
  const SPEAKING_THRESHOLD = 20;

  // Auto-start listening when component mounts and has permissions
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

  // React to Redux state changes
  useEffect(() => {
    if (isMicrophoneListening) {
      startListening();
    } else {
      stopListening();
    }
  }, [isMicrophoneListening]);

  // Restart when device changes (only if currently listening)
  useEffect(() => {
    if (isMicrophoneListening && selectedInputDeviceId) {
      startListening();
    }
  }, [selectedInputDeviceId]);

  const setupAudioVisualization = (stream: MediaStream) => {
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

      const updateAudioLevel = () => {
        if (analyserRef.current) {
          analyserRef.current.getByteFrequencyData(dataArray);
          const average = dataArray.reduce((a, b) => a + b) / dataArray.length;
          setAudioLevel(average);

          // Voice Activity Detection
          handleVoiceActivity(average);

          animationRef.current = requestAnimationFrame(updateAudioLevel);
        }
      };

      updateAudioLevel();
    } catch (error) {
      console.error("Error setting up audio visualization:", error);
    }
  };

  const handleVoiceActivity = (level: number) => {
    const levelPercentage = (level / 128) * 100;

    // Don't start recording if backend is processing
    if (isProcessingRef.current) {
      return;
    }

    // User started speaking
    if (levelPercentage > SPEAKING_THRESHOLD && !isSpeakingRef.current) {
      isSpeakingRef.current = true;
      setIsSpeaking(true);

      // Clear any existing silence timeout
      if (silenceTimeoutRef.current) {
        clearTimeout(silenceTimeoutRef.current);
        silenceTimeoutRef.current = null;
      }

      // Start recording if not already recording
      if (!isRecordingRef.current) {
        startRecording();
      }
    }

    // User is speaking - reset silence timer
    if (levelPercentage > SPEAKING_THRESHOLD && isSpeakingRef.current) {
      if (silenceTimeoutRef.current) {
        clearTimeout(silenceTimeoutRef.current);
      }

      // Set new timeout for silence detection
      silenceTimeoutRef.current = setTimeout(() => {
        handleSilenceDetected();
      }, SILENCE_DURATION);
    }

    // Complete silence
    if (levelPercentage <= SILENCE_THRESHOLD && isSpeakingRef.current) {
      if (!silenceTimeoutRef.current) {
        silenceTimeoutRef.current = setTimeout(() => {
          handleSilenceDetected();
        }, SILENCE_DURATION);
      }
    }
  };

  const handleSilenceDetected = () => {
    isSpeakingRef.current = false;
    setIsSpeaking(false);

    // Clear the silence timeout
    if (silenceTimeoutRef.current) {
      clearTimeout(silenceTimeoutRef.current);
      silenceTimeoutRef.current = null;
    }

    // Check MediaRecorder state
    const recorder = mediaRecorderRef.current;
    if (
      recorder &&
      (recorder.state === "recording" || recorder.state === "paused")
    ) {
      stopRecording();
    }
  };

  const startRecording = () => {
    if (
      !streamRef.current ||
      isRecordingRef.current ||
      isProcessingRef.current
    ) {
      return;
    }

    try {
      // Clear previous chunks at start
      audioChunksRef.current = [];

      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : "audio/ogg";

      const mediaRecorder = new MediaRecorder(streamRef.current, {
        mimeType,
        audioBitsPerSecond: 128000,
      });

      mediaRecorder.ondataavailable = (event: BlobEvent) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        // Update BOTH state and ref
        isRecordingRef.current = false;
        setIsRecording(false);

        // Then send audio
        if (audioChunksRef.current.length > 0) {
          await sendAudioToBackend();
        }

        mediaRecorderRef.current = null;
      };

      mediaRecorder.onerror = (event: Event) => {
        console.error("❌ MediaRecorder error:", event);
        isRecordingRef.current = false;
        setIsRecording(false);
        audioChunksRef.current = [];
      };

      // Request data every 100ms
      mediaRecorder.start(100);
      mediaRecorderRef.current = mediaRecorder;
      isRecordingRef.current = true;
      setIsRecording(true);
      setRecordingStartTime(Date.now());
    } catch (error) {
      console.error("❌ Error starting recording:", error);
      isRecordingRef.current = false;
      setIsRecording(false);
    }
  };

  const stopRecording = () => {
    const recorder = mediaRecorderRef.current;

    if (!recorder || recorder.state === "inactive") {
      return;
    }

    // Enforce minimum recording duration
    const recordingDuration = Date.now() - recordingStartTime;
    if (recordingDuration < 500) {
      return;
    }

    try {
      if (recorder.state === "recording" || recorder.state === "paused") {
        recorder.stop();
      }
    } catch (error) {
      console.error("❌ Error stopping recording:", error);
      setIsRecording(false);
      mediaRecorderRef.current = null;
    }
  };

  const sendAudioToBackend = async () => {
    // Validate we have audio data
    if (audioChunksRef.current.length === 0) {
      return;
    }

    if (!socket || !isConnected) {
      console.error("❌ Socket not connected");
      audioChunksRef.current = [];
      return;
    }

    // Check if already processing
    if (isProcessingRef.current) {
      audioChunksRef.current = [];
      return;
    }

    try {
      // Combine all chunks into a single blob
      const audioBlob = new Blob(audioChunksRef.current, {
        type: mediaRecorderRef.current?.mimeType || "audio/webm;codecs=opus",
      });

      // Validate audio size
      if (audioBlob.size < 1000) {
        audioChunksRef.current = [];
        return;
      }

      // Set processing state BEFORE sending
      isProcessingRef.current = true;
      setIsProcessing(true);

      // Safety timeout: reset after 30 seconds if no response
      processingTimeoutRef.current = setTimeout(() => {
        console.warn("⏰ Processing timeout - resetting state");
        isProcessingRef.current = false;
        setIsProcessing(false);
      }, 30000);

      // Convert to Base64
      const base64Audio = await blobToBase64(audioBlob);

      // Send to backend
      emit("send-user-voice-query", {
        audio: base64Audio,
        mimeType: audioBlob.type,
        timestamp: Date.now(),
        duration: audioChunksRef.current.length * 100,
        userId: "guest",
      });
    } catch (error) {
      console.error("❌ Error sending audio:", error);
      // Reset processing state on error
      isProcessingRef.current = false;
      setIsProcessing(false);
      if (processingTimeoutRef.current) {
        clearTimeout(processingTimeoutRef.current);
        processingTimeoutRef.current = null;
      }
    } finally {
      // ALWAYS clear chunks after sending
      audioChunksRef.current = [];
    }
  };

  // Listen for query results to reset processing state
  useEffect(() => {
    if (socket && isConnected) {
      const resetProcessing = () => {
        // Clear timeout
        if (processingTimeoutRef.current) {
          clearTimeout(processingTimeoutRef.current);
          processingTimeoutRef.current = null;
        }

        // Reset processing state
        isProcessingRef.current = false;
        setIsProcessing(false);
      };

      // Listen to ALL possible completion events
      const handleQueryResult = () => resetProcessing();
      const handleTTSEnd = () => resetProcessing();
      const handleQueryError = () => resetProcessing();
      const handleError = () => resetProcessing();

      // Register all listeners
      on("query-result", handleQueryResult);
      on("tts-end", handleTTSEnd);
      on("query-error", handleQueryError);
      on("error", handleError);

      return () => {
        off("query-result", handleQueryResult);
        off("tts-end", handleTTSEnd);
        off("query-error", handleQueryError);
        off("error", handleError);
      };
    }
  }, [socket, isConnected, on, off]);

  // Helper function to convert Blob to Base64
  const blobToBase64 = (blob: Blob): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        if (typeof reader.result === "string") {
          const base64 = reader.result.split(",")[1];
          resolve(base64);
        } else {
          reject(new Error("Failed to convert blob to base64"));
        }
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  };

  const startListening = async () => {
    try {
      // Stop existing stream first and wait a moment
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

      // Small delay to ensure previous streams are fully released
      await new Promise(resolve => setTimeout(resolve, 100));

      const deviceId = selectedInputDeviceId || audioInputDevices[0]?.deviceId;

      // Try with preferred device first
      const getConstraints = (useExact: boolean): MediaStreamConstraints => ({
        audio: deviceId && useExact
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

      // Try with exact deviceId first
      try {
        stream = await navigator.mediaDevices.getUserMedia(getConstraints(true));
      } catch (exactError: any) {
        console.warn("⚠️ Exact device failed, trying with ideal preference:", exactError.message);
        
        // Fallback: try with ideal (flexible) deviceId
        try {
          stream = await navigator.mediaDevices.getUserMedia(getConstraints(false));
        } catch (idealError: any) {
          console.warn("⚠️ Ideal device failed, trying any available mic:", idealError.message);
          
          // Final fallback: try any available microphone
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
      
      // Provide more helpful error message
      if (error.name === "NotReadableError") {
        console.error("💡 Tip: The microphone may be in use by another app. Close other apps using the mic and try again.");
      } else if (error.name === "NotAllowedError") {
        console.error("💡 Tip: Microphone permission was denied. Please allow microphone access.");
      } else if (error.name === "NotFoundError") {
        console.error("💡 Tip: No microphone found. Please connect a microphone.");
      }
      
      if (isMicrophoneListening) {
        dispatch(toggleMicrophoneListening());
      }
    }
  };

  const stopListening = async () => {
    // Stop recording if active
    if (isRecordingRef.current && mediaRecorderRef.current) {
      stopRecording();

      // Wait briefly for the recording to finish
      await new Promise((resolve) => setTimeout(resolve, 300));
    }

    // Clear silence timeout
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

    if (streamRef.current) {
      streamRef.current
        .getTracks()
        .forEach((track: MediaStreamTrack) => track.stop());
      streamRef.current = null;
    }
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopListening();
    };
  }, []);

  const handleDeviceChange = (deviceId: string) => {
    dispatch(setSelectedInputDeviceId(deviceId));
  };

  const handleToggleListening = () => {
    dispatch(toggleMicrophoneListening());
  };

  const levelPercentage = Math.min((audioLevel / 128) * 100, 100);

  if (!hasPermissions) {
    return (
      <div className="w-64 bg-gray-800 rounded-lg shadow-lg p-4">
        <div className="text-center text-white">
          <p className="text-sm mb-2">Microphone access needed</p>
          <Button
            onClick={() => {
              // Trigger permission request
            }}
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
