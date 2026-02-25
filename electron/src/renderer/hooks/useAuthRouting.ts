import { useEffect, useState, useRef } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { tokenRefreshManager } from "@/lib/auth/tokenRefreshManager";
import { getCurrentUser } from "@/store/features/auth/authThunks";

export function useAuthRouting() {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const location = useLocation();
  const [isLoading, setIsLoading] = useState(true);
  const { isAuthenticated, user } = useAppSelector((state) => state.auth);
  
  const initStarted = useRef(false);
  const authTriggered = useRef(false);

  useEffect(() => {
    if (initStarted.current) return;
    initStarted.current = true;

    const checkAuth = async () => {
      try {
        const token = await tokenRefreshManager.getValidAccessToken();
        
        if (!token) {
          setIsLoading(false);
          return;
        }

        // We have a token, fetch user profile
        await dispatch(getCurrentUser()).unwrap();
      } catch (error) {
        console.error("Auth check failed:", error);
      } finally {
        setIsLoading(false);
      }
    };

    checkAuth();
  }, [dispatch]);

  // Handle successful auth routing side-effects
  useEffect(() => {
    if (!isLoading && !authTriggered.current) {
      authTriggered.current = true;
      
      // Ensure we don't dispatch Main Window actions from the Secondary (AI Panel) Window
      if (location.pathname !== "/ai-panel") {
        if (isAuthenticated) {
          console.log("🚀 Auth Success - Switching to AI Panel");
          window.electronApi.onAuthSuccess();
          
          // Navigate to /home seamlessly so when user opens from Tray, it shows Home
          navigate("/home", { replace: true });
        } else {
          console.log("⚠️ Auth Failed/Missing - Revealing Main Window");
          window.electronApi.onAuthFailure();
        }
      } else {
        console.log("🚀 Auth checks passed for Secondary Window");
      }
    }
  }, [isLoading, isAuthenticated, navigate, location.pathname]);

  return { isLoading, isAuthenticated, user };
}
