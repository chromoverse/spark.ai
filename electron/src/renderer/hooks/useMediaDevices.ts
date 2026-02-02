import { useState, useEffect, useCallback } from "react";
import type { IMediaDevices, IMediaPermissions } from "../../../types";

// Shared hook for loading devices (reusable)
export const useMediaDevices = () => {
  const [devices, setDevices] = useState<IMediaDevices>({
    audioInputs: [],
    audioOutputs: [],
    videoInputs: [],
  });
  const [permissions, setPermissions] = useState<IMediaPermissions>({
    camera: false,
    microphone: false,
    speaker: false,
  });
  const [isLoading, setIsLoading] = useState(true); // Start as true

  // Check if all required permissions are granted
  const hasPermissions =
    permissions.camera && permissions.microphone && permissions.speaker;

  const loadDevices = useCallback(async () => {
    try {
      console.log("🔄 Loading media devices...");
      setIsLoading(true);

      // Check permissions WITHOUT requesting (non-intrusive)
      const permissionStatus = await window.electronApi.checkMediaPermission();
      console.log("📋 Permissions:", permissionStatus);
      setPermissions(permissionStatus);

      // Load devices regardless of permissions
      const mediaDevices = await window.electronApi.getMediaDevices();
      console.log("📱 Media devices loaded:", mediaDevices);
      setDevices(mediaDevices);
    } catch (error) {
      console.error("❌ Error loading devices:", error);
      setDevices({
        audioInputs: [],
        audioOutputs: [],
        videoInputs: [],
      });
      setPermissions({
        camera: false,
        microphone: false,
        speaker: false,
      });
    } finally {
      setIsLoading(false);
      console.log("✅ Device loading complete");
    }
  }, []);

  const requestPermissions = useCallback(async () => {
    try {
      console.log("🔐 Requesting permissions...");
      setIsLoading(true);

      // This WILL trigger browser permission prompts
      const permissionStatus = await window.electronApi.requestMediaPermissions();
      console.log("📋 Permissions result:", permissionStatus);
      setPermissions(permissionStatus);

      // Reload devices after permissions are granted
      if (permissionStatus.camera && permissionStatus.microphone) {
        await loadDevices();
      }
    } catch (error) {
      console.error("❌ Error requesting permissions:", error);
    } finally {
      setIsLoading(false);
    }
  }, [loadDevices]);

  // Load devices on mount
  useEffect(() => {
    loadDevices();
  }, [loadDevices]);

  return {
    devices,
    permissions, // ← NEW: return full permissions object
    hasPermissions, // ← Returns true only if ALL permissions granted
    isLoading,
    loadDevices,
    requestPermissions,
  };
};
