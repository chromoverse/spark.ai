import { createAsyncThunk } from "@reduxjs/toolkit";
import type { IBrainSession } from "@root/types";
import { resetUser, setUser, type AuthUser } from "./authSlice";
import { setBrainSettings } from "../brain/brainSlice";

export function toAuthUser(user: IBrainSession["user"] | { id: string; email: string; name: string | null }): AuthUser {
  return { _id: user.id, email: user.email, fullName: user.name ?? undefined };
}

/** Loads the signed-in user + settings from the brain. Resolves null when signed out;
 * rejects with the brain's persona-voiced error when it can't be reached. */
export const getCurrentUser = createAsyncThunk<IBrainSession | null, void, { rejectValue: string }>(
  "auth/getCurrentUser",
  async (_, { dispatch, rejectWithValue }) => {
    const res = await window.electronApi.brain.getSession();
    if (!res.ok) return rejectWithValue(res.error.message);
    if (!res.data) {
      dispatch(resetUser());
      dispatch(setBrainSettings(null));
      return null;
    }
    dispatch(setUser(toAuthUser(res.data.user)));
    dispatch(setBrainSettings(res.data.settings));
    return res.data;
  },
);
