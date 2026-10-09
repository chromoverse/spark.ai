import { useEffect, useState, useRef } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
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
        // Signed out → null; brain unreachable → rejects. Either way the sign-in screen shows.
        await dispatch(getCurrentUser()).unwrap();
      } catch (error) {
        console.warn("Brain session check failed:", error);
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
      if (location.pathname !== "/ai-panel" && location.pathname !== "/auth/onboarding") {
        if (isAuthenticated && user) {
          // v2 has no onboarding flag yet (R5 brings onboarding back), so go straight in.
          window.electronApi.onAuthSuccess();
          navigate("/home", { replace: true });
        } else if (!isAuthenticated) {
          console.log("⚠️ Auth Failed/Missing - Revealing Main Window");
          window.electronApi.onAuthFailure();
        }
      } else {
        console.log("🚀 Auth checks intentionally paused on AI Panel / onboarding");
      }
    }
  }, [isLoading, isAuthenticated, user, navigate, location.pathname]);

  return { isLoading, isAuthenticated, user };
}
