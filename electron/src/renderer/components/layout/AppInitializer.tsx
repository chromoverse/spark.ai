import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { useMediaDevices } from "@/hooks/useMediaDevices";
import {
  setDevices,
  setHasDevicePermissions,
  setIsDevicesAlreadyFetchedTrue,
  setSelectedCameraDeviceId,
  setSelectedInputDeviceId,
} from "@/store/features/device/deviceSlice";
import {
  toggleMicrophoneListening,
  toggleCameraOn,
  setMicrophoneListening,
} from "@/store/features/localState/localSlice";
import Welcome from "@/pages/Welcome";
import { useAuthRouting } from "@/hooks/useAuthRouting";

export default function AppInitializer({
  children,
}: {
  children: React.ReactNode;
}) {
  const dispatch = useAppDispatch();
  const location = useLocation();

  const { isLoading, isAuthenticated } = useAuthRouting();
  const {
    isDevicesAlreadyFetched,
    audioInputDevices,
    videoInputDevices,
    selectedInputDeviceId,
    selectedCameraDeviceId,
  } = useAppSelector((state) => state.device);
  const { isMicrophoneListening, isCameraOn } = useAppSelector(
    (state) => state.localState,
  );
  const {
    devices,
    hasPermissions,
    isLoading: isDeviceLoading,
  } = useMediaDevices();

  // Sync Media State to Tray
  useEffect(() => {
    window.electronApi.updateMediaState({
      micOn: isMicrophoneListening,
      cameraOn: isCameraOn,
      audioInputs: audioInputDevices,
      videoInputs: videoInputDevices,
      selectedInputDeviceId: selectedInputDeviceId,
      selectedCameraDeviceId: selectedCameraDeviceId,
    });
  }, [
    isMicrophoneListening,
    isCameraOn,
    audioInputDevices,
    videoInputDevices,
    selectedInputDeviceId,
    selectedCameraDeviceId,
  ]);

  // Listen to Tray Media Toggles and Global Shortcuts
  useEffect(() => {
    const unsub = window.electronApi.onTrayMediaToggle(({ type }) => {
      if (type === "MIC") {
        dispatch(toggleMicrophoneListening());
      } else if (type === "CAMERA") {
        dispatch(toggleCameraOn());
      }
    });

    // Listen to global shortcut Ctrl/Cmd + Shift + M for mic toggle
    const unsubMicMute = window.electronApi.onMicMuteToggle(() => {
      console.log("🎤 Global shortcut triggered: Toggle Microphone");
      dispatch(toggleMicrophoneListening());
    });

    const unsubMicControl = window.electronApi.onMicControl(({ action, source }) => {
      console.log(`🎤 Mic control command received: ${action} (${source ?? "main"})`);

      if (action === "toggle") {
        dispatch(toggleMicrophoneListening());
        return;
      }

      dispatch(setMicrophoneListening(action === "unmute"));
    });

    const unsubDeviceSelect = window.electronApi.onTrayDeviceSelect(
      ({ type, deviceId }) => {
        if (type === "MIC") {
          dispatch(setSelectedInputDeviceId(deviceId));
        } else if (type === "CAMERA") {
          dispatch(setSelectedCameraDeviceId(deviceId));
        }
      },
    );

    return () => {
      unsub();
      unsubMicMute();
      unsubMicControl();
      unsubDeviceSelect();
    };
  }, [dispatch]);

  // Device Initialization logic (only if not already fetched)
  useEffect(() => {
    if (!isLoading && isAuthenticated && !isDevicesAlreadyFetched) {
      console.log("🎧 Waiting for devices...");
    }
  }, [isLoading, isAuthenticated, isDevicesAlreadyFetched]);

  // Effect to sync device state to Redux when it becomes available
  // This runs whenever the useMediaDevices hook updates
  useEffect(() => {
    if (isDevicesAlreadyFetched || isDeviceLoading) return;

    if (hasPermissions && devices.audioInputs.length > 0) {
      console.log("💾 Syncing devices to Redux store");
      dispatch(setDevices(devices));
      dispatch(setHasDevicePermissions(hasPermissions));

      // Auto-select first available devices if none selected
      // Note: checking Redux state here via thunk/slice access might be needed if we want to be 100% safe against overwriting user preference,
      // but typically at init time, if nothing is selected, we pick default.
      // For now, simplistically dispatching updates.

      // Use a slight delay or check if we actually need to update to avoid render loops if dependencies aren't perfect
      dispatch(setIsDevicesAlreadyFetchedTrue());
    }
  }, [
    devices,
    hasPermissions,
    isDeviceLoading,
    isDevicesAlreadyFetched,
    dispatch,
  ]);

  // Show loading screen while initializing
  if (isLoading) {
    if (location.pathname === "/ai-panel") {
      // The AI Panel should be empty/transparent while loading, not showing the full AuthLander bg
      return null;
    }
    return <Welcome isLoading={true} />;
  }

  return <>{children}</>;
}
