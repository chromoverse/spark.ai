import { configureStore } from "@reduxjs/toolkit";
import deviceReducer from "./features/device/deviceSlice"
import localStateReducer from "./features/localState/localSlice";
import authReducer from "./features/auth/authSlice"
import brainReducer from "./features/brain/brainSlice"

export const store = configureStore({
  reducer: {
    device: deviceReducer,
    localState: localStateReducer,
    auth: authReducer,
    brain: brainReducer,
  },
});

export type AppDispatch = typeof store.dispatch;
export type RootState = ReturnType<typeof store.getState>;
