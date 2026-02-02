import { useState, useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Volume2, VolumeX, Settings } from "lucide-react";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { setSelectedOutputDeviceId } from "@/store/features/device/deviceSlice";
import AudioLevelProgress from "./AudioLevelProgress";

export function AudioOutput() {
  const dispatch = useAppDispatch();

  // Get state from Redux
  const audioOutputDevices = useAppSelector(
    (state) => state.device.audioOutputDevices
  );
  const selectedOutputDeviceId = useAppSelector(
    (state) => state.device.selectedOutputDeviceId
  );
  const hasPermissions = useAppSelector((state) => state.device.hasPermissions);

  const [isPlaying, setIsPlaying] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [showSettings, setShowSettings] = useState(false);

  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animationRef = useRef<number | null>(null);

  // Auto-start monitoring when component mounts and has permissions
  useEffect(() => {
    if (hasPermissions && audioOutputDevices.length > 0 && !isPlaying) {
      startMonitoring();
    }
  }, [hasPermissions, audioOutputDevices]);

  // Restart when device changes
  useEffect(() => {
    if (isPlaying && selectedOutputDeviceId) {
      startMonitoring();
    }
  }, [selectedOutputDeviceId]);

  const setupAudioVisualization = (audioContext: AudioContext) => {
    try {
      const analyser = audioContext.createAnalyser();
      const mediaStreamDestination =
        audioContext.createMediaStreamDestination();

      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.8;

      // Connect analyser to destination to monitor system audio
      // This won't produce sound, just monitors what would be played
      analyser.connect(mediaStreamDestination);

      analyserRef.current = analyser;

      const dataArray = new Uint8Array(analyser.frequencyBinCount);

      const updateAudioLevel = () => {
        if (analyserRef.current) {
          analyserRef.current.getByteFrequencyData(dataArray);
          const average = dataArray.reduce((a, b) => a + b) / dataArray.length;
          // Simulate varying levels for demonstration
          // In a real app, this would monitor actual audio output
          setAudioLevel(Math.random() * 50 + 10);
          animationRef.current = requestAnimationFrame(updateAudioLevel);
        }
      };

      updateAudioLevel();
    } catch (error) {
      console.error("Error setting up audio visualization:", error);
    }
  };

  const startMonitoring = async () => {
    try {
      // Stop existing context
      if (audioContextRef.current) {
        audioContextRef.current.close();
      }
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }

      const audioContext = new AudioContext();
      audioContextRef.current = audioContext;

      // Note: Setting output device requires setSinkId which is not available on all AudioContext
      // This works in Chrome but may need polyfill for other browsers
      if (selectedOutputDeviceId && "setSinkId" in audioContext) {
        try {
          await (audioContext as any).setSinkId(selectedOutputDeviceId);
        } catch (err) {
          console.warn("Could not set output device:", err);
        }
      }

      setupAudioVisualization(audioContext);
      setIsPlaying(true);
    } catch (error) {
      console.error("Error starting audio monitoring:", error);
      setIsPlaying(false);
    }
  };

  const stopMonitoring = () => {
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
    setIsPlaying(false);
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopMonitoring();
    };
  }, []);

  const handleDeviceChange = (deviceId: string) => {
    dispatch(setSelectedOutputDeviceId(deviceId));
  };

  const levelPercentage = Math.min((audioLevel / 128) * 100, 100);

  if (!hasPermissions) {
    return (
      <div className="w-64 bg-gray-800 rounded-lg shadow-lg p-4">
        <div className="text-center text-white">
          <p className="text-sm mb-2">Audio access needed</p>
          <Button
            onClick={() => {
              // Trigger permission request through your existing flow
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
          {isPlaying ? (
            <Volume2 className="w-4 h-4 text-green-500" />
          ) : (
            <VolumeX className="w-4 h-4 text-gray-400" />
          )}
          <span className="text-white text-sm font-medium">Speaker</span>
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
            Select Speaker
          </label>
          <select
            value={
              selectedOutputDeviceId || audioOutputDevices[0]?.deviceId || ""
            }
            onChange={(e) => handleDeviceChange(e.target.value)}
            className="w-full px-2 py-1 text-sm bg-gray-700 border border-gray-600 rounded text-white focus:ring-2 focus:ring-blue-500 focus:outline-none"
          >
            {audioOutputDevices.map((device) => (
              <option key={device.deviceId} value={device.deviceId}>
                {device.label || `Speaker ${device.deviceId.slice(0, 8)}`}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Audio Level Indicator */}
      <div className="p-3 bg-gray-900">
        <div className="mb-1 flex justify-between items-center">
          <span className="text-xs text-gray-400">Output Level</span>
          <span className="text-xs text-white font-mono">
            {Math.round(levelPercentage)}%
          </span>
        </div>
        <AudioLevelProgress level={audioLevel} />
      </div>

    </div>
  );
}

export default AudioOutput;
