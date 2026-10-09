import { createSlice } from "@reduxjs/toolkit";
import type{ PayloadAction } from "@reduxjs/toolkit";
import type { IUser } from "@shared/user.types";

// v2 sign-in only knows id, email and name. v1 pages still read IUser fields, so the rest stay
// optional until the R2 UI rewrite drops IUser.
export type AuthUser = Partial<IUser> & { _id: string; email: string };

interface AuthState {
    user: AuthUser | null;
    isAuthenticated: boolean;
    isLoading: boolean;
    errorMessage: string | null;
    success: boolean
}

const initialState: AuthState =  {
    user : null,
    isAuthenticated: false,
    isLoading: false,
    errorMessage: null,
    success: false
}

const authSlice = createSlice({
    name: "auth",
    initialState,
    reducers:{
        setUser : (state, action : PayloadAction<AuthUser>) => {
            state.user = action.payload
            if(action.payload) state.isAuthenticated = true
        },
        resetUser :  (state) => {
            state.user = null
            state.isAuthenticated = false
        },
        setSuccess: (state,action:PayloadAction<boolean>) => {
            state.success = action.payload
        },
        setLoading : (state , action: PayloadAction<boolean>) => {
            state.isLoading = action.payload
        },
        setErrorMessage : (state, action: PayloadAction<string>) => {
            state.errorMessage = action.payload
        },
    }
})

export const {
setUser,resetUser,setErrorMessage,setLoading,setSuccess
} = authSlice.actions

export default authSlice.reducer
