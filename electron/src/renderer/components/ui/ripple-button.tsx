import React, { useEffect, useState } from "react";
import type { MouseEvent } from "react";

import { cn } from "@/lib/utils";

interface RippleButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  rippleColor?: string;
  duration?: string;
}

export const RippleButton = React.forwardRef<HTMLButtonElement, RippleButtonProps>(
  (
    {
      className,
      children,
      rippleColor = "#ADD8E6",
      duration = "600ms",
      onClick,
      ...props
    },
    ref
  ) => {
    const [buttonRipples, setButtonRipples] = useState<
      Array<{ x: number; y: number; size: number; key: number }>
    >([]);
    const [isPressed, setIsPressed] = useState(false);
    const [isHovered, setIsHovered] = useState(false);

    const handleClick = (event: MouseEvent<HTMLButtonElement>) => {
      createRipple(event);

      // Thread button animation: small -> large -> normal
      setIsPressed(true);
      setTimeout(() => setIsPressed(false), 300);

      onClick?.(event);
    };

    const createRipple = (event: MouseEvent<HTMLButtonElement>) => {
      const button = event.currentTarget;
      const rect = button.getBoundingClientRect();
      const size = Math.max(rect.width, rect.height);
      const x = event.clientX - rect.left - size / 2;
      const y = event.clientY - rect.top - size / 2;

      const newRipple = { x, y, size, key: Date.now() };
      setButtonRipples((prevRipples) => [...prevRipples, newRipple]);
    };

    useEffect(() => {
      if (buttonRipples.length > 0) {
        const lastRipple = buttonRipples[buttonRipples.length - 1];
        const timeout = setTimeout(() => {
          setButtonRipples((prevRipples) =>
            prevRipples.filter((ripple) => ripple.key !== lastRipple.key)
          );
        }, parseInt(duration));
        return () => clearTimeout(timeout);
      }
    }, [buttonRipples, duration]);

    return (
      <button
        className={cn(
          "relative flex cursor-pointer items-center justify-center overflow-hidden rounded-xl px-5 py-2 text-center font-medium transition-all duration-300 backdrop-blur-3xl border",
          className
        )}
        onClick={handleClick}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        ref={ref}
        style={{
          background: isHovered
            ? "rgba(255, 255, 255, 0.15)"
            : "rgba(255, 255, 255, 0.08)",
          borderColor: isHovered
            ? "rgba(255, 255, 255, 0.3)"
            : "rgba(255, 255, 255, 0.18)",
          boxShadow: isPressed
            ? "0 0 30px rgba(173, 216, 230, 0.6), inset 0 0 20px rgba(173, 216, 230, 0.4), 0 4px 20px rgba(0, 0, 0, 0.2)"
            : isHovered
            ? "0 12px 40px rgba(0, 0, 0, 0.15), 0 0 35px rgba(173, 216, 230, 0.5), inset 0 0 10px rgba(255, 255, 255, 0.1)"
            : "0 8px 32px rgba(0, 0, 0, 0.1), 0 0 20px rgba(173, 216, 230, 0.3)",
          transform: isPressed
            ? "scale(0.92)"
            : isHovered
            ? "scale(1.02) translateY(-2px)"
            : "scale(1)",
          color: "#ffffff",
          textShadow: isHovered
            ? "0 0 15px rgba(173, 216, 230, 0.8), 0 0 5px rgba(255, 255, 255, 0.5)"
            : "0 0 10px rgba(173, 216, 230, 0.5)",
        }}
        {...props}
      >
        <style>
          {`
            @keyframes ripple {
              0% {
                opacity: 1;
                transform: scale(0);
              }
              100% {
                opacity: 0;
                transform: scale(2);
              }
            }
            
            @keyframes threadClick {
              0% {
                transform: scale(1);
              }
              50% {
                transform: scale(0.92);
              }
              75% {
                transform: scale(1.05);
              }
              100% {
                transform: scale(1);
              }
            }
          `}
        </style>

        <div
          className="relative z-10 text-gray-800"
          style={{
            animation: isPressed ? "threadClick 300ms ease-out" : "none",
          }}
        >
          {children}
        </div>

        <span className="pointer-events-none absolute inset-0">
          {buttonRipples.map((ripple) => (
            <span
              className="absolute rounded-full pointer-events-none"
              key={ripple.key}
              style={{
                width: `${ripple.size}px`,
                height: `${ripple.size}px`,
                top: `${ripple.y}px`,
                left: `${ripple.x}px`,
                backgroundColor: rippleColor,
                opacity: 0.4,
                transform: "scale(0)",
                animation: `ripple ${duration} ease-out`,
                filter: "blur(2px)",
              }}
            />
          ))}
        </span>

        {/* Glassy glow overlay */}
        <div
          className="absolute inset-0 pointer-events-none rounded-xl"
          style={{
            background:
              "radial-gradient(circle at 50% 0%, rgba(255, 255, 255, 0.15), transparent 70%)",
            transition: "opacity 0.3s",
            opacity: isPressed ? 0.3 : 0.6,
          }}
        />
      </button>
    );
  }
);

RippleButton.displayName = "RippleButton";
