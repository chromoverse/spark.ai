import React from 'react'
import { AudioInput } from "@/components/local/device/AudioInput";
import { VideoInputComponent } from "@/components/local/device/VideoInput";

export default function RightPanel() {
  return (
    <div className="flex w-full h-full relative">
      <div className="absolute bottom-1 left-5">
        <VideoInputComponent />
      </div>
    </div>
  );
}
