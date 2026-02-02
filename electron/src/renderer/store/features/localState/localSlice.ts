import { createSlice } from "@reduxjs/toolkit";
import type{ PayloadAction } from "@reduxjs/toolkit";

interface LocalState {
  isMicrophoneListening: boolean;
  isCameraOn: boolean;
  isRecording: boolean;
  isSpeaking: boolean;
  lastRecordingTimestamp: number | null;
  isClientOnline: boolean;
  isServerOnline: boolean;
}

const initialState: LocalState = {
  isMicrophoneListening: true,
  isCameraOn: false,
  isRecording: false,
  isSpeaking: false,
  lastRecordingTimestamp: null,
  isClientOnline: true,
  isServerOnline: true,
};

const localSlice = createSlice({
  name: "local",
  initialState,
  reducers: {
    toggleMicrophoneListening: (state) => {
      state.isMicrophoneListening = !state.isMicrophoneListening;
      // Reset recording states when microphone is turned off
      if (!state.isMicrophoneListening) {
        state.isRecording = false;
        state.isSpeaking = false;
      }
    },
    toggleCameraOn: (state) => {
      state.isCameraOn = !state.isCameraOn;
    },
    setIsRecording: (state, action: PayloadAction<boolean>) => {
      state.isRecording = action.payload;
      if (action.payload) {
        state.lastRecordingTimestamp = Date.now();
      }
    },
    setIsSpeaking: (state, action: PayloadAction<boolean>) => {
      state.isSpeaking = action.payload;
    },
    resetRecordingState: (state) => {
      state.isRecording = false;
      state.isSpeaking = false;
    },
    setClientOnline: (state) => {
      state.isClientOnline = true
    },
    setClientOffline: (state) => {
      state.isClientOnline = false;
    },
    setServerOnline: (state) => {
      state.isServerOnline = true;
    },
    setServerOffline: (state) => {
      state.isServerOnline = false;
    },
    resetLocalState: (state) => {
      state.isMicrophoneListening = true;
      state.isCameraOn = false;
      state.isRecording = false;
      state.isSpeaking = false;
      state.lastRecordingTimestamp = null;
      state.isClientOnline = true;
      state.isServerOnline = true;
    },

  },
});

export const {
  toggleMicrophoneListening,
  toggleCameraOn,
  setIsRecording,
  setIsSpeaking,
  resetRecordingState,
  setClientOnline,
  setClientOffline,
  setServerOnline,
  setServerOffline,
  resetLocalState
} = localSlice.actions;

export default localSlice.reducer;
