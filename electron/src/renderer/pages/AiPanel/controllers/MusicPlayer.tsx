import { useState } from 'react';
import { Play, Pause, SkipBack, SkipForward, Music } from 'lucide-react';
import type { ControllerProps } from '../types';

interface MusicState {
  isPlaying: boolean;
  currentTime: number;
  duration: number;
  title: string;
}

export function MusicPlayer({ isActive }: ControllerProps) {
  const [music, setMusic] = useState<MusicState>({
    isPlaying: true,
    currentTime: 45,
    duration: 180,
    title: 'Lofi Hip Hop',
  });

  if (!isActive) return null;

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const progress = (music.currentTime / music.duration) * 100;

  const togglePlay = () => {
    setMusic((prev) => ({ ...prev, isPlaying: !prev.isPlaying }));
  };

  return (
    <div className="flex flex-col gap-2 px-4 w-full">
      {/* Info */}
      <div className="flex items-center justify-between text-[11px] text-indigo-200/70">
        <span className="font-medium">{music.title}</span>
        <span className="tabular-nums">
          {formatTime(music.currentTime)} / {formatTime(music.duration)}
        </span>
      </div>

      {/* Controls */}
      <div className="flex items-center justify-center gap-2.5">
        <button
          className="w-[30px] h-[30px] rounded-full flex items-center justify-center
                     bg-indigo-300/10 border border-indigo-300/15
                     hover:bg-indigo-300/20 active:scale-95
                     transition-all duration-200 outline-none"
          aria-label="Previous"
        >
          <SkipBack className="w-3.5 h-3.5 text-indigo-100" />
        </button>

        <button
          onClick={togglePlay}
          className="w-10 h-10 rounded-full flex items-center justify-center
                     bg-indigo-300/20 border border-indigo-300/15
                     hover:bg-indigo-300/30 active:scale-95
                     transition-all duration-200 outline-none"
          aria-label="Play/Pause"
        >
          {music.isPlaying ? (
            <Pause className="w-[18px] h-[18px] text-indigo-100" />
          ) : (
            <Play className="w-[18px] h-[18px] text-indigo-100 ml-0.5" />
          )}
        </button>

        <button
          className="w-[30px] h-[30px] rounded-full flex items-center justify-center
                     bg-indigo-300/10 border border-indigo-300/15
                     hover:bg-indigo-300/20 active:scale-95
                     transition-all duration-200 outline-none"
          aria-label="Next"
        >
          <SkipForward className="w-3.5 h-3.5 text-indigo-100" />
        </button>
      </div>

      {/* Progress */}
      <div className="w-full h-1 bg-indigo-300/10 rounded-sm overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-indigo-400 to-indigo-300 transition-[width] duration-300 ease-out"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}

// Plugin config
export const musicPlayerPlugin = {
  id: 'music-player',
  name: 'Music',
  icon: <Music className="w-4 h-4" />,
  component: MusicPlayer,
  order: 2,
};
