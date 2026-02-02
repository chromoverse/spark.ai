import { useState } from 'react';
import { Volume2, VolumeOff, Video, VideoOff, MessageCircle, Gamepad2 } from 'lucide-react';
import type { ControllerProps } from '../types';
import { OpenAppsButton } from '../components/OpenAppsButton';

export function BasicControls({ isActive }: ControllerProps) {
  const [isMuted, setIsMuted] = useState(false);
  const [isVideoOff, setIsVideoOff] = useState(false);

  if (!isActive) return null;

  return (
    <div className="flex items-center justify-center gap-3 px-4 py-2">
      {/* Mute Toggle */}
      <button
        onClick={() => setIsMuted(!isMuted)}
        className={`
          w-9 h-9 rounded-full flex items-center justify-center
          bg-[var(--accent-color)] bg-opacity-10 border border-[var(--border-color)]
          hover:bg-opacity-20 hover:border-[var(--accent-color)] hover:border-opacity-25
          hover:-translate-y-0.5 active:scale-95
          transition-all duration-200 outline-none
        `}
        aria-label="Toggle microphone"
      >
        {isMuted ? (
          <VolumeOff className="w-[18px] h-[18px] text-red-400" />
        ) : (
          <Volume2 className="w-[18px] h-[18px] text-[var(--text-primary)]" />
        )}
      </button>

      {/* Video Toggle */}
      <button
        onClick={() => setIsVideoOff(!isVideoOff)}
        className={`
          w-9 h-9 rounded-full flex items-center justify-center
          bg-[var(--accent-color)] bg-opacity-10 border border-[var(--border-color)]
          hover:bg-opacity-20 hover:border-[var(--accent-color)] hover:border-opacity-25
          hover:-translate-y-0.5 active:scale-95
          transition-all duration-200 outline-none
        `}
        aria-label="Toggle video"
      >
        {isVideoOff ? (
          <VideoOff className="w-[18px] h-[18px] text-red-400" />
        ) : (
          <Video className="w-[18px] h-[18px] text-[var(--text-primary)]" />
        )}
      </button>

      {/* Chat Mode */}
      <button
        className={`
          w-9 h-9 rounded-full flex items-center justify-center
          bg-[var(--accent-color)] bg-opacity-10 border border-[var(--border-color)]
          hover:bg-opacity-20 hover:border-[var(--accent-color)] hover:border-opacity-25
          hover:-translate-y-0.5 active:scale-95
          transition-all duration-200 outline-none
        `}
        aria-label="Switch mode"
      >
        <MessageCircle className="w-[18px] h-[18px] text-[var(--text-primary)]" />
      </button>

      {/* Open Apps Button */}
      <OpenAppsButton />
    </div>
  );
}

// Plugin config
export const basicControlsPlugin = {
  id: 'basic-controls',
  name: 'Controls',
  icon: <Gamepad2 className="w-4 h-4" />,
  component: BasicControls,
  order: 1,
};
