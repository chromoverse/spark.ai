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

// Demo component to show it in action
function AudioLevelShower() {
  const [level, setLevel] = React.useState(0);

  React.useEffect(() => {
    const interval = setInterval(() => {
      setLevel((prev) => {
        const next = prev + Math.random() * 20 - 10;
        return Math.max(0, Math.min(100, next));
      });
    }, 200);

    return () => clearInterval(interval);
  }, []);

  return (
    <div className="min-h-screen bg-gray-900 flex items-center justify-center p-8">
      <div className="w-full max-w-md space-y-6">
        <div className="bg-gray-800 rounded-lg p-6 space-y-4">
          <h2 className="text-white text-xl font-semibold">
            Audio Level Monitor
          </h2>

          <AudioLevelProgress level={level} />

          <div className="flex justify-between items-center">
            <span className="text-xs text-gray-400">Audio Level</span>
            <span className="text-xs text-white font-mono">
              {Math.round(level)}%
            </span>
          </div>

          <div className="grid grid-cols-4 gap-2 pt-4">
            <button
              onClick={() => setLevel(0)}
              className="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-white text-sm rounded"
            >
              0%
            </button>
            <button
              onClick={() => setLevel(30)}
              className="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-white text-sm rounded"
            >
              30%
            </button>
            <button
              onClick={() => setLevel(60)}
              className="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-white text-sm rounded"
            >
              60%
            </button>
            <button
              onClick={() => setLevel(100)}
              className="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-white text-sm rounded"
            >
              100%
            </button>
          </div>
        </div>

        <div className="bg-gray-800 rounded-lg p-4">
          <h3 className="text-white text-sm font-medium mb-3">Color Scale</h3>
          <div className="space-y-2 text-sm">
            <div className="flex items-center gap-3">
              <div className="w-8 h-3 bg-blue-900 rounded" />
              <span className="text-gray-300">0-25%: Dark Blue</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="w-8 h-3 bg-blue-700 rounded" />
              <span className="text-gray-300">25-50%: Medium Blue</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="w-8 h-3 bg-blue-500 rounded" />
              <span className="text-gray-300">50-75%: Bright Blue</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="w-8 h-3 bg-blue-400 rounded" />
              <span className="text-gray-300">75-100%: Light Blue</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
