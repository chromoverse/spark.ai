import { createContext, useContext } from "react";

// Context + hook live apart from the provider component so Fast Refresh can hot-swap it.

export interface SparkTTSContextProps {
  speak: (text: string) => void;
  stop: () => void;
  isSpeaking: boolean;
  queueLength: number;
  audioLevel: number;
}

export const SparkTTSContext = createContext<SparkTTSContextProps | null>(null);

export const useSparkTTS = () => {
  const ctx = useContext(SparkTTSContext);
  if (!ctx) throw new Error("useSparkTTS must be used inside SparkTTSProvider");
  return ctx;
};
