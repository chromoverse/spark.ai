// lib/axios/axiosConfig.ts

import axios, { AxiosError} from "axios";
import type { AxiosRequestConfig, AxiosResponse } from "axios";


// Standardized response format
export interface ApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  access_token?: string;  // ✅ Added for Electron responses
  refresh_token?: string; // ✅ Added for Electron responses
  error?: {
    message: string;
    code?: string;
    status?: number;
    details?: unknown;
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

// v1 server client. v2 tokens never reach the renderer, so these calls go out unauthenticated
// and the v1 pages show their error states until the R2 UI moves them to the brain.
axiosInstance.interceptors.response.use(
  (response: AxiosResponse) => response.data,
  (error: AxiosError) => Promise.reject(handleErrorResponse(error)),
);

/** GET that returns the body. The response interceptor already unwraps it, which axios's own
 * types don't know, so callers name the body shape they expect here. */
export async function getJson<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  return (await axiosInstance.get(url, config)) as unknown as T;
}

// Centralized error handler
function handleErrorResponse(error: AxiosError): ApiResponse {
  const response = error.response;
  // console.log("response fo error from axosConfig", response)
  const errorData = response?.data as
    | { message?: string; code?: string; error_code?: string; details?: unknown; errors?: unknown }
    | undefined;

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
