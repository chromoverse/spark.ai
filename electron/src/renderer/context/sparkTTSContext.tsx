import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useCallback,
} from "react";
import { useSocket } from "@/context/socketContextProvider";

interface SparkTTSContextProps {
  speak: (text: string) => void;
  stop: () => void;
  isSpeaking: boolean;
  queueLength: number;
}

const SparkTTSContext = createContext<SparkTTSContextProps | null>(null);

/**
 * Converts a raw Socket.IO binary payload into a Uint8Array backed by ArrayBuffer.
 */
function toUint8Array(data: unknown): Uint8Array | null {
  if (!data) return null;

  if (data instanceof Uint8Array) {
    const copy = new Uint8Array(data.byteLength);
    copy.set(data);
    return copy;
  }

  if (data instanceof ArrayBuffer) {
    return new Uint8Array(data);
  }

  if (typeof Buffer !== "undefined" && Buffer.isBuffer(data)) {
    const copy = new Uint8Array(data.byteLength);
    for (let i = 0; i < data.byteLength; i++) {
      copy[i] = data[i];
    }
    return copy;
  }

  return null;
}

export const SparkTTSProvider = ({
  children,
}: {
  children: React.ReactNode;
}) => {
  const { socket, on, off } = useSocket();

  // ── state ──
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [queueLength, setQueueLength] = useState(0);

  // Current stream's chunks
  const chunkQueueRef = useRef<Uint8Array[]>([]);

  // Pending streams waiting to play
  const pendingStreamsRef = useRef<
    Array<{ streamId: string; chunks: Uint8Array[]; ended: boolean }>
  >([]);

  const activeStreamIdRef = useRef<string | null>(null);
  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const isPlayingChunkRef = useRef<boolean>(false);
  const stoppedRef = useRef<boolean>(false);
  const audioContextRef = useRef<AudioContext | null>(null);

  // Track if current stream has received tts-end
  const currentStreamEndedRef = useRef<boolean>(false);

  // Track when last audio ended to prevent overlap
  const lastAudioEndTimeRef = useRef<number>(0);

  // ── Initialize AudioContext ──
  useEffect(() => {
    const initAudioContext = () => {
      if (!audioContextRef.current) {
        try {
          const AudioContextClass =
            window.AudioContext || (window as any).webkitAudioContext;
          if (AudioContextClass) {
            audioContextRef.current = new AudioContextClass();
          }
        } catch (err) {
          console.warn("AudioContext creation failed:", err);
        }
      }
    };

    const handleInteraction = () => {
      initAudioContext();
    };

    document.addEventListener("click", handleInteraction, { once: true });
    document.addEventListener("touchstart", handleInteraction, { once: true });

    return () => {
      document.removeEventListener("click", handleInteraction);
      document.removeEventListener("touchstart", handleInteraction);
      if (audioContextRef.current) {
        audioContextRef.current.close();
      }
    };
  }, []);

  // ── Move to next pending stream ──
  const moveToNextStream = useCallback(() => {
    console.log(
      `🔄 moveToNextStream: pending count = ${pendingStreamsRef.current.length}`
    );

    if (pendingStreamsRef.current.length === 0) {
      // Nothing left to play
      console.log("✅ All streams completed");
      activeStreamIdRef.current = null;
      currentStreamEndedRef.current = false;
      setIsSpeaking(false);
      setQueueLength(0);
      return;
    }

    const next = pendingStreamsRef.current.shift();
    if (!next) return;

    console.log(
      `▶️ Starting next stream [${next.streamId}] with ${next.chunks.length} chunks`
    );

    activeStreamIdRef.current = next.streamId;
    chunkQueueRef.current = [...next.chunks];
    currentStreamEndedRef.current = next.ended;
    setQueueLength(pendingStreamsRef.current.length);

    // SMART DELAY: Only if streams arrived too quickly
    const now = Date.now();
    const timeSinceLastAudio = now - lastAudioEndTimeRef.current;
    
    // Only add delay if last audio JUST finished (within 30ms)
    // This prevents overlap while keeping natural flow
    if (timeSinceLastAudio < 30) {
      const delay = 30 - timeSinceLastAudio;
      console.log(`⏳ Micro-delay ${delay}ms to prevent overlap`);
      setTimeout(() => {
        if (!isPlayingChunkRef.current && !stoppedRef.current) {
          playNextChunk();
        }
      }, delay);
    } else {
      // Natural timing - start immediately
      if (!isPlayingChunkRef.current) {
        playNextChunk();
      }
    }
  }, []);

  // ── Play next WAV chunk ──
  const playNextChunk = useCallback(() => {
    if (stoppedRef.current) {
      console.log("⏹️ Stopped, not playing");
      return;
    }

    if (isPlayingChunkRef.current) {
      console.log("⏸️ Already playing a chunk, waiting...");
      return;
    }

    // Check if current stream has chunks to play
    if (chunkQueueRef.current.length > 0) {
      const wav = chunkQueueRef.current.shift();
      if (!wav) return;

      console.log(
        `🎵 Playing chunk from stream [${activeStreamIdRef.current}] (${chunkQueueRef.current.length} remaining)`
      );

      const arrayBuffer = new Uint8Array(wav).buffer as ArrayBuffer;
      const blob = new Blob([arrayBuffer], { type: "audio/wav" });
      const url = URL.createObjectURL(blob);

      // Force cleanup previous audio
      if (audioElementRef.current) {
        const prev = audioElementRef.current;
        prev.pause();
        prev.currentTime = 0;
        prev.src = "";
        prev.onended = null;
        prev.onerror = null;
      }

      const audio = new Audio(url);
      audioElementRef.current = audio;
      isPlayingChunkRef.current = true;

      audio.preload = "auto";
      audio.volume = 1.0;

      // Resume AudioContext if suspended
      if (audioContextRef.current?.state === "suspended") {
        audioContextRef.current.resume().catch((err) => {
          console.warn("Failed to resume AudioContext:", err);
        });
      }

      audio.onended = () => {
        console.log("✅ Chunk playback ended");
        isPlayingChunkRef.current = false;
        lastAudioEndTimeRef.current = Date.now();
        URL.revokeObjectURL(url);

        // NO DELAY - immediately continue
        // The natural audio ending is the timing we want
        if (!stoppedRef.current) {
          playNextChunk();
        }
      };

      audio.onerror = () => {
        console.error("❌ Audio chunk playback error");
        isPlayingChunkRef.current = false;
        lastAudioEndTimeRef.current = Date.now();
        URL.revokeObjectURL(url);
        if (!stoppedRef.current) {
          playNextChunk();
        }
      };

      audio.play().catch((err) => {
        console.error("❌ Play failed:", err);
        isPlayingChunkRef.current = false;
        lastAudioEndTimeRef.current = Date.now();
        URL.revokeObjectURL(url);
        if (!stoppedRef.current) {
          playNextChunk();
        }
      });
      return;
    }

    // Current stream exhausted, but has it ended?
    if (currentStreamEndedRef.current) {
      console.log(
        `✅ Current stream [${activeStreamIdRef.current}] fully played and ended`
      );
      moveToNextStream();
    } else {
      console.log(
        `⏳ Current stream [${activeStreamIdRef.current}] has no chunks, waiting for more...`
      );
      // Wait for more chunks or tts-end
    }
  }, [moveToNextStream]);

  // ── PUBLIC: speak ──
  const speak = useCallback((_text: string) => {
    console.log(`ℹ️ speak() called for: "${_text.substring(0, 40)}..."`);
  }, []);

  // ── PUBLIC: stop ──
  const stop = useCallback(() => {
    console.log("🛑 Stopping all TTS audio");
    stoppedRef.current = true;

    if (audioElementRef.current) {
      audioElementRef.current.pause();
      audioElementRef.current.currentTime = 0;
      audioElementRef.current.src = "";
      audioElementRef.current = null;
    }

    chunkQueueRef.current = [];
    pendingStreamsRef.current = [];
    activeStreamIdRef.current = null;
    isPlayingChunkRef.current = false;
    currentStreamEndedRef.current = false;
    setQueueLength(0);
    setIsSpeaking(false);

    setTimeout(() => {
      stoppedRef.current = false;
    }, 100);
  }, []);

  // ── SOCKET LISTENERS ──
  useEffect(() => {
    if (!socket) return;

    const handleStart = (payload: { streamId: string; text?: string }) => {
      const { streamId } = payload;
      console.log(`🎤 tts-start [${streamId}]: "${payload.text}"`);

      if (stoppedRef.current) return;

      // If no active stream, start this one immediately
      if (!activeStreamIdRef.current) {
        console.log(`▶️ Starting stream [${streamId}] as active`);
        activeStreamIdRef.current = streamId;
        chunkQueueRef.current = [];
        currentStreamEndedRef.current = false;
        setIsSpeaking(true);
        setQueueLength(0);
      } else {
        // Queue it
        console.log(
          `📥 Queueing stream [${streamId}] (active: ${activeStreamIdRef.current})`
        );
        pendingStreamsRef.current.push({
          streamId,
          chunks: [],
          ended: false,
        });
        setQueueLength(pendingStreamsRef.current.length);
      }
    };

    const handleChunk = (payload: { streamId: string; data: unknown }) => {
      if (stoppedRef.current) return;

      const { streamId, data } = payload;
      const bytes = toUint8Array(data);

      if (!bytes || bytes.byteLength === 0) {
        console.warn("⚠️ Received empty/unreadable tts-chunk");
        return;
      }

      console.log(
        `📦 tts-chunk [${streamId}]: ${bytes.byteLength} bytes`
      );

      // Add to active stream
      if (streamId === activeStreamIdRef.current) {
        chunkQueueRef.current.push(bytes);
        console.log(
          `✅ Added to active queue (${chunkQueueRef.current.length} chunks now)`
        );

        // If not currently playing, start
        if (!isPlayingChunkRef.current) {
          console.log("▶️ Starting playback");
          playNextChunk();
        }
        return;
      }

      // Add to pending stream
      const pending = pendingStreamsRef.current.find(
        (s) => s.streamId === streamId
      );
      if (pending) {
        pending.chunks.push(bytes);
        console.log(
          `✅ Added to pending stream [${streamId}] (${pending.chunks.length} chunks)`
        );
      } else {
        console.warn(
          `⚠️ tts-chunk for unknown stream [${streamId}], creating pending entry`
        );
        pendingStreamsRef.current.push({
          streamId,
          chunks: [bytes],
          ended: false,
        });
        setQueueLength(pendingStreamsRef.current.length);
      }
    };

    const handleEnd = (payload: {
      streamId: string;
      success: boolean;
      chunks?: number;
      error?: string;
    }) => {
      const { streamId, success } = payload;
      console.log(
        `✅ tts-end [${streamId}] success=${success} chunks=${payload.chunks}`
      );

      if (!success) {
        console.error(`❌ TTS stream [${streamId}] failed: ${payload.error}`);
      }

      // Mark active stream as ended
      if (streamId === activeStreamIdRef.current) {
        console.log(`✅ Active stream [${streamId}] marked as ended`);
        currentStreamEndedRef.current = true;

        // If no chunks left and not playing, move to next immediately
        if (
          chunkQueueRef.current.length === 0 &&
          !isPlayingChunkRef.current
        ) {
          console.log("⏭️ No chunks left, moving to next stream");
          moveToNextStream();
        } else {
          console.log(
            `⏳ Waiting for ${chunkQueueRef.current.length} chunks to finish`
          );
        }
        return;
      }

      // Mark pending stream as ended
      const pending = pendingStreamsRef.current.find(
        (s) => s.streamId === streamId
      );
      if (pending) {
        console.log(`✅ Pending stream [${streamId}] marked as ended`);
        pending.ended = true;
      } else {
        console.warn(`⚠️ tts-end for unknown stream [${streamId}]`);
      }
    };

    const handleError = (error: { success?: boolean; error?: string }) => {
      console.error("❌ response-tts error:", error);
    };

    on("tts-start", handleStart);
    on("tts-chunk", handleChunk);
    on("tts-end", handleEnd);
    on("response-tts", handleError);

    return () => {
      off("tts-start", handleStart);
      off("tts-chunk", handleChunk);
      off("tts-end", handleEnd);
      off("response-tts", handleError);
    };
  }, [socket, on, off, playNextChunk, moveToNextStream]);

  return (
    <SparkTTSContext.Provider
      value={{
        speak,
        stop,
        isSpeaking,
        queueLength,
      }}
    >
      {children}
    </SparkTTSContext.Provider>
  );
};

export const useSparkTTS = () => {
  const ctx = useContext(SparkTTSContext);
  if (!ctx) throw new Error("useSparkTTS must be used inside SparkTTSProvider");
  return ctx;
};