import { useEffect, useMemo, useState, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { useMediaDevices } from "@/hooks/useMediaDevices";
import { 
  setDevices, 
  setHasDevicePermissions, 
  setIsDevicesAlreadyFetchedTrue, 
  setSelectedCameraDeviceId, 
  setSelectedInputDeviceId, 
  setSelectedOutputDeviceId 
} from "@/store/features/device/deviceSlice";
import { tokenRefreshManager } from "@/lib/auth/tokenRefreshManager";
import { getCurrentUser } from "@/store/features/auth/authThunks";
import Welcome from "@/pages/Welcome";

export default function AppInitializer({ children }: { children: React.ReactNode }) {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const location = useLocation();
  
  // Use local state for initialization to avoid redux updates causing re-renders of this component
  const [isInitializing, setIsInitializing] = useState(true);
  const { isDevicesAlreadyFetched } = useAppSelector((state) => state.device);
  const { devices, hasPermissions, isLoading: isDeviceLoading } = useMediaDevices();
  
  // Prevent double initialization in strict mode or rapid re-mounts
  const initializationStarted = useRef(false);

  // Check if we are on a "public" looking URL
  const isPublicRoute = useMemo(() => {
    return ["/welcome", "/auth/sign-in", "/auth/sign-up"].some(
      path => location.pathname.startsWith(path)
    );
  }, [location.pathname]);

  // Main initialization logic
  useEffect(() => {
    if (initializationStarted.current) return;
    initializationStarted.current = true;

    const initializeApp = async () => {
      console.log("🚀 Starting App Initialization...");
      const startTime = Date.now();

      try {
        // 1. Check Authentication
        const token = await tokenRefreshManager.getValidAccessToken();
        
        if (!token) {
          console.log("❌ No valid token found.");
          setIsInitializing(false);
          // Only redirect if we are at root or a protected route that shouldn't be accessed directly
          // We let the router guards handle the actual redirection logic mostly, 
          // but if we are at root '/' we should go to public welcome
          if (location.pathname === '/') {
             navigate('/welcome', { replace: true });
          }
          return;
        }

        console.log("✅ Token found, fetching user...");
        await dispatch(getCurrentUser());

        // 2. Device Initialization (only if not already fetched)
        if (!isDevicesAlreadyFetched) {
           console.log("🎧 Waiting for devices...");
           // We rely on the useMediaDevices hook which runs in parallel.
           // We just wait a tick to ensure the hook has had a chance to start working if needed
           // or we can just proceed and let the device state update asynchronously.
           // However, for a "smooth" feel, we might want to wait for device permission check at least.
        } else {
            console.log("✅ Devices already fetched earlier.");
        }

        // 3. Maximize window if authenticated
        window.electronApi.sendFrameAction("MAXIMIZE");

        console.log(`✨ Initialization completed in ${Date.now() - startTime}ms`);
      } catch (error) {
        console.error("❌ Initialization failed:", error);
      } finally {
        setIsInitializing(false);
      }
    };

    initializeApp();
  }, [dispatch, isDevicesAlreadyFetched, navigate, location.pathname]);

  // Effect to sync device state to Redux when it becomes available
  // This runs whenever the useMediaDevices hook updates
  useEffect(() => {
    if (isDevicesAlreadyFetched || isDeviceLoading) return;

    if (hasPermissions && devices.audioInputs.length > 0) {
        console.log("💾 Syncing devices to Redux store");
        dispatch(setDevices(devices));
        dispatch(setHasDevicePermissions(hasPermissions));
        
        // Auto-select first available devices if none selected
        // Note: checking Redux state here via thunk/slice access might be needed if we want to be 100% safe against overwriting user preference,
        // but typically at init time, if nothing is selected, we pick default.
        // For now, simplistically dispatching updates.
        
        // Use a slight delay or check if we actually need to update to avoid render loops if dependencies aren't perfect
        dispatch(setIsDevicesAlreadyFetchedTrue());
    }
  }, [devices, hasPermissions, isDeviceLoading, isDevicesAlreadyFetched, dispatch]);


  // Show loading screen while initializing
  if (isInitializing) {
    return <Welcome isLoading={true} />;
  }

  return <>{children}</>;
}
