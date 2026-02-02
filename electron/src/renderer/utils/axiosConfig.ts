// lib/axios/axiosConfig.ts

import axios, { AxiosError} from "axios";
import type { AxiosResponse, InternalAxiosRequestConfig } from "axios";
import { toast } from "sonner";
import { tokenRefreshManager } from "@/lib/auth/tokenRefreshManager";

// Standardized response format
export interface ApiResponse<T = any> {
  success: boolean;
  data?: T;
  access_token?: string;  // ✅ Added for Electron responses
  refresh_token?: string; // ✅ Added for Electron responses
  error?: {
    message: string;
    code?: string;
    status?: number;
    details?: any;
  };
  status: number;
  message?: string;
}

const axiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1",
  timeout: 10000,
  headers: {
    "Content-Type": "application/json",
  },
});

// Request interceptor
axiosInstance.interceptors.request.use(
  async (config: InternalAxiosRequestConfig) => {
    try {
      const token = await tokenRefreshManager.getValidAccessToken();
      if (token) {
        config.headers["Authorization"] = `Bearer ${token}`;
      }
      return config;
    } catch (error) {
      console.error("Failed to attach token:", error);
      return config;
    }
  },
  (error) => Promise.reject(error)
);

// Response interceptor - transform responses
axiosInstance.interceptors.response.use(
  async (response: AxiosResponse) => {
    // Extract and store tokens if present (for Electron)
    const responseData = response.data;
    
    if (responseData.access_token) {
      await window.electronApi.saveToken("access_token", responseData.access_token)
    }
    
    if (responseData.refresh_token) {
      await window.electronApi.saveToken("refresh_token", responseData.refresh_token)
    }
    
    // Return the entire response data (including tokens if present)
    return response.data as any;
  },
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

    // Handle 401 errors - token refresh logic
    if (error.response?.status === 401 && !originalRequest._retry) {
      
      // If already refreshing, wait in queue
      if (tokenRefreshManager.isCurrentlyRefreshing) {
        try {
          const newToken = await tokenRefreshManager.addToQueue();
          if (originalRequest.headers) {
            originalRequest.headers["Authorization"] = `Bearer ${newToken}`;
          }
          return axiosInstance(originalRequest);
        } catch (refreshError) {
          return Promise.reject(handleErrorResponse(refreshError as AxiosError));
        }
      }

      originalRequest._retry = true;

      try {
        const newToken = await tokenRefreshManager.refreshAccessToken();
        if (originalRequest.headers) {
          originalRequest.headers["Authorization"] = `Bearer ${newToken}`;
        }
        return axiosInstance(originalRequest);
      } catch (refreshError) {
        return Promise.reject(handleErrorResponse(refreshError as AxiosError));
      }
    }

    // Handle all other errors
    return Promise.reject(handleErrorResponse(error));
  }
);

// Centralized error handler
function handleErrorResponse(error: AxiosError): ApiResponse {
  const response = error.response;
  // console.log("response fo error from axosConfig", response)
  const errorData: any = response?.data;

  // Build standardized error response
  const standardizedError: ApiResponse = {
    success: false,
    status: response?.status || 500,
    error: {
      message: errorData?.message || error.message || "An unexpected error occurred",
      code: errorData?.code || errorData?.error_code || error.code,
      status: response?.status,
      details: errorData?.details || errorData?.errors || null,
    },
  };

  // Show toast notification based on error type
  // if (!response) {
  //   // Network error
  //   toast.error("Network Error: Please check your connection.");
  //   standardizedError.error!.message = "Network error. Please check your connection.";
  // } else if (response.status === 401) {
  //   toast.error(standardizedError.error?.message || "Authentication failed. Please login again.");
  // } else if (response.status === 403) {
  //   toast.error(standardizedError.error?.message || "Access denied. You don't have permission.");
  // } else if (response.status === 404) {
  //   toast.error(standardizedError.error?.message);
  // } else if (response.status >= 500) {
  //   toast.error(standardizedError.error?.message || "Server error. Please try again later.");
  // } else {
  //   // Show custom error message from server
  //   toast.error(standardizedError.error!.message);
  // }

  return standardizedError;
}

export default axiosInstance;
export { axiosInstance };
