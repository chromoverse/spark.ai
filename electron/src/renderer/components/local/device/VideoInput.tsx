import { useState, useEffect, useRef } from "react";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { Button } from "@/components/ui/button";
import { Settings, Video, VideoOff } from "lucide-react";
import type { IMediaDevice } from "types";
import { setSelectedCameraDeviceId } from "@/store/features/device/deviceSlice";
import { toggleCameraOn } from "@/store/features/localState/localSlice";

export function VideoInputComponent() {
  const dispatch = useAppDispatch();

  // Get state from Redux
  const videoInputDevices = useAppSelector(
    (state) => state.device.videoInputDevices
  );
  const selectedCameraDeviceId = useAppSelector(
    (state) => state.device.selectedCameraDeviceId
  );
  const hasPermissions = useAppSelector((state) => state.device.hasPermissions);
  const isCameraOn = useAppSelector((state) => state.localState.isCameraOn);

  const [showSettings, setShowSettings] = useState(false);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  // Auto-start stream when component mounts and has permissions
  useEffect(() => {
    if (hasPermissions && videoInputDevices.length > 0 && !isCameraOn) {
      dispatch(toggleCameraOn());
    }
  }, [hasPermissions, videoInputDevices]);

  // React to Redux state changes
  useEffect(() => {
    if (isCameraOn) {
      startStream();
    } else {
      stopStream();
    }
  }, [isCameraOn]);

  // Auto-restart stream when selected device changes (only if camera is on)
  useEffect(() => {
    if (isCameraOn && selectedCameraDeviceId) {
      startStream();
    }
  }, [selectedCameraDeviceId]);

  const startStream = async () => {
    try {
      if (!videoRef.current) return;

      // Stop existing stream
      if (streamRef.current) {
        streamRef.current
          .getTracks()
          .forEach((track: MediaStreamTrack) => track.stop());
      }

      const deviceId = selectedCameraDeviceId || videoInputDevices[0]?.deviceId;

      const constraints = {
        video: deviceId
          ? {
              deviceId: { exact: deviceId },
              // width: { ideal: 640 },
              // height: { ideal: 480 },
            }
          : {
              // width: { ideal: 640 },
              // height: { ideal: 480 },
            },
        audio: false,
      };

      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      streamRef.current = stream;
      videoRef.current.srcObject = stream;
    } catch (error) {
      console.error("Error starting stream:", error);
      // If there's an error, turn off the camera state
      if (isCameraOn) {
        dispatch(toggleCameraOn());
      }
    }
  };

  const stopStream = () => {
    if (streamRef.current) {
      streamRef.current
        .getTracks()
        .forEach((track: MediaStreamTrack) => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopStream();
    };
  }, []);

  const handleDeviceChange = (deviceId: string) => {
    dispatch(setSelectedCameraDeviceId(deviceId));
  };

  const handleToggleCamera = () => {
    dispatch(toggleCameraOn());
  };

  if (!hasPermissions) {
    return (
      <div className="w-64 bg-gray-800 rounded-lg shadow-lg p-4">
        <div className="text-center text-white">
          <p className="text-sm mb-2">Camera access needed</p>
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
        <span className="text-white text-sm font-medium">Camera</span>
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
            Select Camera
          </label>
          <select
            value={
              selectedCameraDeviceId || videoInputDevices[0]?.deviceId || ""
            }
            onChange={(e) => handleDeviceChange(e.target.value)}
            className="w-full px-2 py-1 text-sm bg-gray-700 border border-gray-600 rounded text-white focus:ring-2 focus:ring-blue-500 focus:outline-none"
          >
            {videoInputDevices.map((device: IMediaDevice) => (
              <option key={device.deviceId} value={device.deviceId}>
                {device.label || `Camera ${device.deviceId.slice(0, 8)}`}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Video Preview */}
      <div className="relative bg-black" style={{ aspectRatio: "4/3" }}>
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className="w-full h-full object-cover"
          style={{ transform: "scaleX(-1)" }}
        />
        {!isCameraOn && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-900">
            <p className="text-gray-400 text-sm">No video</p>
          </div>
        )}
        {isCameraOn && (
          <div className="absolute top-2 right-2 px-2 py-1 bg-red-600 rounded text-white text-xs font-bold flex items-center gap-1">
            <div className="w-2 h-2 bg-white rounded-full animate-pulse"></div>
            LIVE
          </div>
        )}
      </div>
    </div>
  );
}

export default VideoInputComponent;
