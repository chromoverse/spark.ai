import { createSlice } from "@reduxjs/toolkit";
import type { IMediaDevice } from "../../../../../types";

// Helper function to safely get from localStorage
const getFromLocalStorage = (key: string): string | null => {
  try {
    console.log(`Retrieving ${key} from localStorage`);
    return localStorage.getItem(key);
  } catch (error) {
    console.error(`Error reading ${key} from localStorage:`, error);
    return null;
  }
};

// Load saved device IDs from localStorage on initialization
const initialState = {
  audioInputDevices: [] as IMediaDevice[],
  audioOutputDevices: [] as IMediaDevice[],
  videoInputDevices: [] as IMediaDevice[],
  selectedInputDeviceId: getFromLocalStorage("selectedInputDeviceId"),
  selectedCameraDeviceId: getFromLocalStorage("selectedCameraDeviceId"),
  selectedOutputDeviceId: getFromLocalStorage("selectedOutputDeviceId"),
  hasPermissions: false,
  isLoading: false,
  isDevicesAlreadyFetched: false,
};

export const deviceSlice = createSlice({
  name: "device",
  initialState,
  reducers: {
    setDevices: (state, action) => {
      state.audioInputDevices = action.payload.audioInputs;
      state.audioOutputDevices = action.payload.audioOutputs;
      state.videoInputDevices = action.payload.videoInputs;
    },
    setSelectedInputDeviceId: (state, action) => {
      try {
        localStorage.setItem("selectedInputDeviceId", action.payload);
      } catch (error) {
        console.error("Error saving selectedInputDeviceId:", error);
      }
      state.selectedInputDeviceId = action.payload;
    },
    setSelectedCameraDeviceId: (state, action) => {
      try {
        localStorage.setItem("selectedCameraDeviceId", action.payload);
      } catch (error) {
        console.error("Error saving selectedCameraDeviceId:", error);
      }
      state.selectedCameraDeviceId = action.payload;
    },
    setSelectedOutputDeviceId: (state, action) => {
      try {
        localStorage.setItem("selectedOutputDeviceId", action.payload);
      } catch (error) {
        console.error("Error saving selectedOutputDeviceId:", error);
      }
      state.selectedOutputDeviceId = action.payload;
    },
    setHasDevicePermissions: (state, action) => {
      state.hasPermissions = action.payload;
    },
    setLoading: (state, action) => {
      state.isLoading = action.payload;
    },
    setIsDevicesAlreadyFetchedTrue: (state) => {
      state.isDevicesAlreadyFetched = true;
    },
    // Optional: Clear saved devices (useful for logout/reset)
    clearSavedDevices: (state) => {
      try {
        localStorage.removeItem("selectedInputDeviceId");
        localStorage.removeItem("selectedCameraDeviceId");
        localStorage.removeItem("selectedOutputDeviceId");
      } catch (error) {
        console.error("Error clearing saved devices:", error);
      }
      state.selectedInputDeviceId = null;
      state.selectedCameraDeviceId = null;
      state.selectedOutputDeviceId = null;
    },
  },
});

export const {
  setDevices,
  setSelectedInputDeviceId,
  setSelectedCameraDeviceId,
  setSelectedOutputDeviceId,
  setHasDevicePermissions,
  setLoading,
  setIsDevicesAlreadyFetchedTrue,
  clearSavedDevices,
} = deviceSlice.actions;

export default deviceSlice.reducer;
