import React, { useEffect, useState } from "react";
import {
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { setClientOffline, setClientOnline } from "@/store/features/localState/localSlice";
import Profile from "./Profile"
import Setting from "./Settings"

// Main Bottom Bar Component
export default function BottomBar() {
  const dispatch = useAppDispatch();
  const [deviceStatus, setDeviceStatus] = useState({
    cpuUsage: 0,
    ramUsage: 0,
    storageData: { total: 0, free: 0, usage: 0 },
  });

  const { isServerOnline, isClientOnline } = useAppSelector(
    (state) => state.localState
  );

  useEffect(() => {
  // Set up listener for continuous updates
    const unsubscribe = window.electronApi.onDeviceUsageStatusChange((data) => {
      setDeviceStatus(data);
    });

    // Initial fetch
    window.electronApi.getDeviceUsageStatus().then((data) => {
      setDeviceStatus(data);
    });

    // Check connectivity
    const updateConnectivity = () => {
      if (window.navigator.onLine) {
        dispatch(setClientOnline());
      } else {
        dispatch(setClientOffline());
      }
    };

    // Initial check
    updateConnectivity();

    // Listen for changes
    window.addEventListener("online", updateConnectivity);
    window.addEventListener("offline", updateConnectivity);

    return () => {
      unsubscribe();
      window.removeEventListener("online", updateConnectivity);
      window.removeEventListener("offline", updateConnectivity);
    };
  }, []);

  return (
    <TooltipProvider delayDuration={300}>
      <div className="w-full h-9 bg-white/5 flex items-center justify-between text-xs text-neutral-400 webkit-drag-nodrag border-t border-white/10 z-999">
        {/* Left - Settings & Profile */}
        <div className="flex items-center gap-1 px-2">
          <Setting />
          <Profile />
        </div>

        {/* Right - Device Usage & Stats */}
        <div className="flex items-center gap-4 px-4">
          {/* Client Connection Status */}
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex items-center gap-1.5 cursor-default">
                {isClientOnline ? (
                  <>
                    <div className="w-1.5 h-1.5 rounded-full bg-green-500 mt-px" />
                    <span className="text-neutral-500">Client</span>
                  </>
                ) : (
                  <>
                    <div className="w-1.5 h-1.5 rounded-full bg-red-500 mt-px" />
                    <span className="text-neutral-500">Client</span>
                  </>
                )}
              </div>
            </TooltipTrigger>
            <TooltipContent side="top">
              <p>
                Status : Client is {isClientOnline ? "online" : "offline"}.{" "}
              </p>
            </TooltipContent>
          </Tooltip>

          {/* Server Connection Status */}
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex items-center gap-1.5 cursor-default">
                {isServerOnline ? (
                  <>
                    <div className="w-1.5 h-1.5 rounded-full bg-green-500 mt-px" />
                    <span className="text-neutral-500">Server</span>
                  </>
                ) : (
                  <>
                    <div className="w-1.5 h-1.5 rounded-full bg-red-500 mt-px" />
                    <span className="text-neutral-500">Server</span>
                  </>
                )}
              </div>
            </TooltipTrigger>
            <TooltipContent side="top">
              <p>
                Status : Server is {isServerOnline ? "connected" : "disconnected"}.{" "}
              </p>
            </TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex items-center gap-1.5 cursor-default">
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  className="text-blue-400"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"
                  />
                </svg>
                <span className="text-neutral-500">
                  {(deviceStatus.cpuUsage * 100).toFixed(1)}%
                </span>
              </div>
            </TooltipTrigger>
            <TooltipContent side="top">
              <p>Spark CPU Usage</p>
            </TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex items-center gap-1.5 cursor-default">
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  className="text-amber-400"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"
                  />
                </svg>
                <span className="text-neutral-500">
                  {(deviceStatus.ramUsage * 100).toFixed(1)}%
                </span>
              </div>
            </TooltipTrigger>
            <TooltipContent side="top">
              <p>Spark RAM Usage</p>
            </TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex items-center gap-1.5 cursor-default">
                <Sparkles size={14} className="text-purple-400" />
                <span className="text-neutral-500">
                  {deviceStatus.storageData.free}GB
                </span>
              </div>
            </TooltipTrigger>
            <TooltipContent side="top">
              <p>Storage Free</p>
            </TooltipContent>
          </Tooltip>
        </div>
      </div>
    </TooltipProvider>
  );
}
