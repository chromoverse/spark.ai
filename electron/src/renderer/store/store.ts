import { configureStore } from "@reduxjs/toolkit";
import deviceReducer from "./features/device/deviceSlice"
import localStateReducer from "./features/localState/localSlice";
import authReducer from "./features/auth/authSlice"

export const store = configureStore({
  reducer: {
    device: deviceReducer,
    localState: localStateReducer,
    auth: authReducer
  },
});

export type AppDispatch = typeof store.dispatch;
export type RootState = ReturnType<typeof store.getState>;
