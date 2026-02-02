import React from "react";
import AudioInput from "../device/AudioInput";
import AudioOutput from "../device/AudioOutput";

export default function LeftPanel() {
  return (
    <div className="w-full h-full flex flex-col items-center py-4 gap-4">
      <span className="w-full text-left pl-6">Devices</span>
      <AudioInput />
      <AudioOutput />
    </div>
  );
}
