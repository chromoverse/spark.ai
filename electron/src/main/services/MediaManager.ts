import { systemPreferences, BrowserWindow } from "electron";
import {
  IMediaDevices,
  IMediaPermissions,
  IMediaDevice,
} from "@root/types";

export async function getMediaDevices(
  mainWindow: BrowserWindow
): Promise<IMediaDevices> {
  try {
    // Get all media devices through the renderer process
    const devices = await mainWindow.webContents.executeJavaScript(`
      navigator.mediaDevices.enumerateDevices()
        .then(devices => devices.map(d => ({
          deviceId: d.deviceId,
          label: d.label,
          kind: d.kind,
          groupId: d.groupId
        })))
    `);

    const audioInputs = devices.filter(
      (d: IMediaDevice) => d.kind === "audioinput"
    );
    const audioOutputs = devices.filter(
      (d: IMediaDevice) => d.kind === "audiooutput"
    );
    const videoInputs = devices.filter(
      (d: IMediaDevice) => d.kind === "videoinput"
    );

    return {
      audioInputs,
      audioOutputs,
      videoInputs,
    };
  } catch (error) {
    console.error("Error getting media devices:", error);
    return {
      audioInputs: [],
      audioOutputs: [],
      videoInputs: [],
    };
  }
}

// Check permissions WITHOUT requesting (no prompts)
export async function checkMediaPermissions(
  mainWindow: BrowserWindow
): Promise<IMediaPermissions> {
  try {
    const result = await mainWindow.webContents.executeJavaScript(`
      Promise.all([
        navigator.permissions.query({ name: 'camera' })
          .then(result => result.state === 'granted')
          .catch(() => false),
        navigator.permissions.query({ name: 'microphone' })
          .then(result => result.state === 'granted')
          .catch(() => false)
      ]).then(([camera, microphone]) => ({ 
        camera, 
        microphone,
        speaker: true // Speakers don't need permission in browsers
      }))
    `);

    console.log("📋 Permission check result:", result);
    return result;
  } catch (error) {
    console.error("Error checking permissions:", error);
    return {
      camera: false,
      microphone: false,
      speaker: false,
    };
  }
}

// Request permissions (WILL trigger browser prompts)
export async function requestMediaPermissions(
  mainWindow: BrowserWindow
): Promise<IMediaPermissions> {
  try {
    console.log("🔐 Requesting media permissions...");

    const result = await mainWindow.webContents.executeJavaScript(`
      Promise.all([
        navigator.mediaDevices.getUserMedia({ video: true })
          .then(stream => {
            console.log("✅ Camera permission granted");
            stream.getTracks().forEach(track => track.stop());
            return true;
          })
          .catch((err) => {
            console.log("❌ Camera permission denied:", err.message);
            return false;
          }),
        navigator.mediaDevices.getUserMedia({ audio: true })
          .then(stream => {
            console.log("✅ Microphone permission granted");
            stream.getTracks().forEach(track => track.stop());
            return true;
          })
          .catch((err) => {
            console.log("❌ Microphone permission denied:", err.message);
            return false;
          })
      ]).then(([camera, microphone]) => ({ 
        camera, 
        microphone,
        speaker: true // Speakers are always available
      }))
    `);

    console.log("🔐 Permission request result:", result);
    return result;
  } catch (error) {
    console.error("Error requesting media permissions:", error);
    return {
      camera: false,
      microphone: false,
      speaker: false,
    };
  }
}

// Legacy function - now uses checkMediaPermissions (non-intrusive)
export async function getMediaPermissions(
  mainWindow: BrowserWindow
): Promise<IMediaPermissions> {
  return checkMediaPermissions(mainWindow);
}

// System-level permission check (macOS only)
export async function checkSystemPermissions(): Promise<IMediaPermissions> {
  let camera = false;
  let microphone = false;
  let speaker = true; // Speakers don't need permissions

  if (process.platform === "darwin") {
    // macOS
    const cameraStatus = systemPreferences.getMediaAccessStatus("camera");
    const micStatus = systemPreferences.getMediaAccessStatus("microphone");

    camera = cameraStatus === "granted";
    microphone = micStatus === "granted";

    console.log("🍎 macOS system permissions:", {
      camera: cameraStatus,
      microphone: micStatus,
    });
  } else if (process.platform === "win32") {
    // Windows - permissions granted at runtime
    camera = true;
    microphone = true;
  } else {
    // Linux and others
    camera = true;
    microphone = true;
  }

  return { camera, microphone, speaker };
}
