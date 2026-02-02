import { useState, useEffect, useMemo } from 'react';
import type { VoiceBubbleProps } from '../types';

export function VoiceBubble({ audioLevel }: VoiceBubbleProps) {
  const [hueRotation, setHueRotation] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setHueRotation((prev) => (prev + 60) % 360);
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  const wavePoints = 28;
  const waves = useMemo(() => {
    return Array.from({ length: wavePoints }, (_, i) => {
      const angle = (i / wavePoints) * Math.PI * 2;
      const intensity = Math.sin(Date.now() / 180 + i * 0.5) * (audioLevel / 100);
      const radius = 18 + intensity * 14;
      return {
        x: 50 + Math.cos(angle) * radius,
        y: 50 + Math.sin(angle) * radius,
      };
    });
  }, [audioLevel]);

  const wavePath = useMemo(() => {
    let d = `M ${waves[0].x} ${waves[0].y}`;
    for (let i = 1; i < waves.length; i++) {
      d += ` L ${waves[i].x} ${waves[i].y}`;
    }
    return d + ' Z';
  }, [waves]);

  const gradientX = 40 + Math.sin(Date.now() / 900) * 12;
  const gradientY = 40 + Math.cos(Date.now() / 1000) * 12;

  return (
    <div className="relative w-9 h-9 select-none">
      <svg viewBox="0 0 100 100" className="w-full h-full">
        <defs>
          <radialGradient id="voice-base-gradient">
            <stop offset="0%" stopColor="#a5b4fc" />
            <stop offset="60%" stopColor="#818cf8" />
            <stop offset="100%" stopColor="#6366f1" />
          </radialGradient>
          <radialGradient
            id="voice-shine-gradient"
            cx={`${gradientX}%`}
            cy={`${gradientY}%`}
          >
            <stop offset="0%" stopColor="#e0e7ff" stopOpacity={0.9} />
            <stop offset="40%" stopColor="#c7d2fe" stopOpacity={0.4} />
            <stop offset="100%" stopColor="transparent" />
          </radialGradient>
          <filter id="voice-bubble-blur">
            <feGaussianBlur stdDeviation={1 + audioLevel / 60} />
          </filter>
          <clipPath id="voice-bubble-clip">
            <circle cx="50" cy="50" r="40" />
          </clipPath>
        </defs>

        {/* Base circle */}
        <circle
          cx="50"
          cy="50"
          r="42"
          fill="url(#voice-base-gradient)"
          style={{
            filter: `hue-rotate(${hueRotation}deg)`,
            transition: 'filter 3s linear',
          }}
        />

        {/* Shine overlay */}
        <circle
          cx="50"
          cy="50"
          r="42"
          fill="url(#voice-shine-gradient)"
          opacity={0.6}
        />

        {/* Wave effect */}
        <g clipPath="url(#voice-bubble-clip)">
          <path
            d={wavePath}
            fill="url(#voice-base-gradient)"
            opacity={0.75}
            filter="url(#voice-bubble-blur)"
          />
        </g>

        {/* Border ring */}
        <circle
          cx="50"
          cy="50"
          r="42"
          fill="none"
          stroke="#e0e7ff"
          strokeWidth={0.6}
          opacity={0.4 + audioLevel / 200}
        />
      </svg>
    </div>
  );
}
