import { createSlice } from "@reduxjs/toolkit";
import type{ PayloadAction } from "@reduxjs/toolkit";
import type { IUser } from "@shared/user.types";

interface AuthState {
    user: IUser | null;
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
        setUser : (state, action : PayloadAction<IUser>) => {
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
