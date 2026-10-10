import { configureStore } from "@reduxjs/toolkit";
import deviceReducer from "./features/device/deviceSlice"
import localStateReducer from "./features/localState/localSlice";
import authReducer from "./features/auth/authSlice"
import brainReducer from "./features/brain/brainSlice"
import sparkReducer from "./features/spark/sparkSlice";

export const store = configureStore({
  reducer: {
    device: deviceReducer,
    localState: localStateReducer,
    auth: authReducer,
    brain: brainReducer,
    spark: sparkReducer,
  },
});

export type AppDispatch = typeof store.dispatch;
export type RootState = ReturnType<typeof store.getState>;
