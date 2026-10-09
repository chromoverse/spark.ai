import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import type { IBrainSettings, IBrainStatus } from "@root/types";

// Live state from the brain's v2 socket (main process → IPC → here).
interface BrainState {
  status: IBrainStatus;
  settings: IBrainSettings | null;
}

const initialState: BrainState = { status: "signed_out", settings: null };

const brainSlice = createSlice({
  name: "brain",
  initialState,
  reducers: {
    setBrainStatus: (state, action: PayloadAction<IBrainStatus>) => {
      state.status = action.payload;
    },
    setBrainSettings: (state, action: PayloadAction<IBrainSettings | null>) => {
      state.settings = action.payload;
    },
    // settings.changed carries only the fields that changed.
    mergeBrainSettings: (state, action: PayloadAction<Partial<IBrainSettings>>) => {
      if (state.settings) Object.assign(state.settings, action.payload);
    },
  },
});

export const { setBrainStatus, setBrainSettings, mergeBrainSettings } = brainSlice.actions;
export default brainSlice.reducer;
