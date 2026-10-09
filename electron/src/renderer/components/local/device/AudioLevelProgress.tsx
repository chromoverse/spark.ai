import React from "react";

interface AudioLevelProgressProps {
  level: number; // 0-100
}

export default function AudioLevelProgress({ level }: AudioLevelProgressProps) {
  // Clamp level between 0 and 100
  const clampedLevel = Math.max(0, Math.min(100, level));

  // Calculate color based on level - blue gets more intense as level increases
  const getBlueIntensity = () => {
    // Map 0-100 to different shades of blue
    if (clampedLevel < 25) return "bg-blue-900";
    if (clampedLevel < 50) return "bg-blue-700";
    if (clampedLevel < 75) return "bg-blue-500";
    return "bg-blue-400";
  };

  return (
    <div className="w-full h-3 bg-gray-700 rounded-full overflow-hidden">
      <div
        className={`h-full transition-all duration-100 ease-out ${getBlueIntensity()}`}
        style={{ width: `${clampedLevel}%` }}
      />
    </div>
  );
}

