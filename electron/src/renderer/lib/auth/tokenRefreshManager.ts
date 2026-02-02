// lib/auth/tokenRefreshManager.ts

import type { ApiResponse } from "@/utils/axiosConfig";
import axios from "axios";
import { toast } from "sonner";

interface TokenRefreshQueueItem {
  resolve: (token: string) => void;
  reject: (error: Error) => void;
}

class TokenRefreshManager {
  private isRefreshing = false;
  private failedQueue: TokenRefreshQueueItem[] = [];
  private refreshPromise: Promise<string> | null = null;

  async getValidAccessToken(): Promise<string> {
    try {
      const currentToken = await window.electronApi.getToken("access_token");
      
      if (!currentToken) {
        throw new Error("No access token found");
      }

      const isExpired = this.isTokenExpired(currentToken);
      const isExpiringSoon = this.isTokenExpiringSoon(currentToken);

      if (!isExpired && !isExpiringSoon) {
        console.log("✅ Token is valid, using existing token");
        return currentToken;
      }

      console.log("⚠️ Token expired or expiring soon, refreshing...");
      return await this.refreshAccessToken();

    } catch (error) {
      console.error("❌ Failed to get valid access token:", error);
      throw error;
    }
  }

  private isTokenExpired(token: string): boolean {
    try {
      const payload = this.decodeJWT(token);
      if (!payload.exp) return true;
      
      const now = Math.floor(Date.now() / 1000);
      return payload.exp < now;
    } catch {
      return true;
    }
  }

  private isTokenExpiringSoon(token: string): boolean {
    try {
      const payload = this.decodeJWT(token);
      if (!payload.exp) return true;
      
      const now = Math.floor(Date.now() / 1000);
      const fiveMinutesFromNow = now + (5 * 60);
      
      return payload.exp < fiveMinutesFromNow;
    } catch {
      return true;
    }
  }

  private decodeJWT(token: string): any {
    try {
      const base64Url = token.split('.')[1];
      const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
      const jsonPayload = decodeURIComponent(
        atob(base64)
          .split('')
          .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
          .join('')
      );
      return JSON.parse(jsonPayload);
    } catch (error) {
      console.error("Failed to decode JWT:", error);
      throw new Error("Invalid token format");
    }
  }

  async refreshAccessToken(): Promise<string> {
    if (this.isRefreshing && this.refreshPromise) {
      console.log("⏳ Token refresh already in progress, waiting...");
      return this.refreshPromise;
    }

    this.isRefreshing = true;

    this.refreshPromise = (async () => {
      try {
        const refreshToken = await window.electronApi.getToken("refresh_token");
        
        if (!refreshToken) {
          throw new Error("No refresh token found");
        }

        console.log("🔄 Refreshing access token...");

        // ✅ FIX: Use fetch instead of axios to avoid interceptor loops
        const response = await fetch(
          `${import.meta.env.VITE_API_BASE_URL}/auth/refresh-token`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ refresh_token: refreshToken }),
          }
        );

        if (!response.ok) {
          const errorData = await response.json();
          throw new Error(errorData.message || "Failed to refresh token");
        }

        const data = await response.json();
        console.log("Response after refreshing token:", data);

        // ✅ FIX: Extract tokens from root level (your API structure)
        const access_token = data.access_token;
        const newRefreshToken = data.refresh_token;

        // ✅ FIX: Better validation
        if (!access_token || typeof access_token !== 'string' || access_token.length < 10) {
          throw new Error("Invalid access token received");
        }

        if (!newRefreshToken || typeof newRefreshToken !== 'string' || newRefreshToken.length < 10) {
          throw new Error("Invalid refresh token received");
        }

        // Save new tokens
        await window.electronApi.saveToken("access_token", access_token);
        await window.electronApi.saveToken("refresh_token", newRefreshToken);

        console.log("✅ Token refreshed successfully");

        // Process queued requests
        this.processQueue(null, access_token);

        return access_token;

      } catch (error: any) {
        console.error("❌ Token refresh failed:", error);
        
        // Process queued requests with error
        this.processQueue(error as Error, null);

        // ✅ FIX: Only delete tokens if it's an auth error (401/403)
        // Don't delete on network errors or server errors
        const shouldClearTokens = 
          error.message?.includes("Invalid") ||
          error.message?.includes("expired") ||
          error.message?.includes("No refresh token") ||
          error.status === 401 ||
          error.status === 403;

        if (shouldClearTokens) {
          console.log("🗑️ Clearing invalid tokens");
          await window.electronApi.deleteToken("access_token");
          await window.electronApi.deleteToken("refresh_token");
          
          // Redirect to login
          toast.error("Session expired. Please login again.");
          // window.location.href = "/auth/lander";
        } else {
          // Network error or server error - keep tokens, just show error
          toast.error("Failed to refresh session. Please try again.");
        }

        throw error;

      } finally {
        this.isRefreshing = false;
        this.refreshPromise = null;
      }
    })();

    return this.refreshPromise;
  }

  addToQueue(): Promise<string> {
    return new Promise((resolve, reject) => {
      this.failedQueue.push({ resolve, reject });
    });
  }

  private processQueue(error: Error | null, token: string | null) {
    this.failedQueue.forEach((item) => {
      if (error) {
        item.reject(error);
      } else if (token) {
        item.resolve(token);
      }
    });

    this.failedQueue = [];
  }

  get isCurrentlyRefreshing(): boolean {
    return this.isRefreshing;
  }
}

export const tokenRefreshManager = new TokenRefreshManager();
