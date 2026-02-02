import { createAsyncThunk } from "@reduxjs/toolkit";
import { setUser,resetUser,setLoading,setErrorMessage, setSuccess } from "./authSlice";
import { axiosInstance, type ApiResponse } from "@/utils/axiosConfig";
import type { IVerifyOTP } from "@shared/auth.types";
import { useNavigate } from "react-router-dom";


export const getCurrentUser = createAsyncThunk(
    "user/getCurrentUser",
    async (_, {dispatch}) => {
        try {
            setLoading(true)
            const response : ApiResponse = await axiosInstance.get("/auth/get-me")
            dispatch(setUser(response.data))
            console.log("user data from thunk", response)
        } catch (error ) {
            const apiError = error as ApiResponse
            console.log("errror", apiError)
            console.log("Error occured while getting current user from authThunk", apiError.message)
        } finally {
            setLoading(false)
        }
    }
)

export const signInUser = createAsyncThunk(
    "auth/signInUser",
    async({email}: {email:string}, {dispatch}) => {
        dispatch(setSuccess(false))
        try {
            setLoading(true)
            const response : ApiResponse = await axiosInstance.post("/auth/sign-in", {email})
            console.log("Signin data from thunk", response)
            dispatch(setSuccess(true))
            return true
        } catch (error ) {
            const apiError = error as ApiResponse
            console.log("errror", apiError)
        } finally {
            setLoading(false)
        }
    }
)

export const verifyOtp = createAsyncThunk(
    "auth/verifyOtp",
    async({otp, email}:IVerifyOTP,{dispatch}) => {
        const navigate = useNavigate()
        dispatch(setSuccess(false))
        try {
            setLoading(true);
            if (!otp || otp.length !== 6) {
                return;
            }
            const response: ApiResponse = await axiosInstance.post("auth/verify-otp", {
               email,
               otp,
            });
            dispatch(setSuccess(true))
            console.log("OTP verification response:", response);
        } catch (error) {
             const apiError = error as ApiResponse
             console.error("Error verifying OTP:", apiError);
        } finally {
             setLoading(false);
        }
    }
)
