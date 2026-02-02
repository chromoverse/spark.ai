import { memo } from "react";
import type { ControllerDotsProps } from "../types";

export const ControllerDots = memo(
  ({ controllers, activeIndex, onSelect }: ControllerDotsProps) => {
    if (controllers.length <= 1) return null;

    return (
      <div className="flex items-center justify-center gap-2 py-2">
        {controllers.map((controller, index) => {
          const isActive = index === activeIndex;
          
          if (controller.icon) {
            return (
              <button
                key={controller.id}
                onClick={() => onSelect(index)}
                className={`
                  flex items-center justify-center transition-all duration-300 rounded-full
                  ${
                    isActive
                      ? "text-[var(--accent-color)] scale-110"
                      : "text-[var(--text-secondary)] opacity-40 hover:opacity-70 hover:text-[var(--accent-color)]"
                  }
                  w-6 h-6
                `}
                aria-label={`Go to ${controller.name}`}
              >
                {controller.icon}
              </button>
            );
          }

          return (
            <button
              key={controller.id}
              onClick={() => onSelect(index)}
              className={`
                w-1.5 h-1.5 rounded-full transition-all duration-300
                ${
                  isActive
                    ? "bg-[var(--accent-color)] w-4"
                    : "bg-[var(--accent-color)] opacity-30 hover:opacity-50"
                }
              `}
              aria-label={`Go to ${controller.name}`}
            />
          );
        })}
      </div>
    );
  },
  (prevProps, nextProps) => {
    // Only re-render if activeIndex changes since controllers prop is unlikely to change structurally
    // But since we use controllers array content for rendering, technically we should check length/ids
    return prevProps.activeIndex === nextProps.activeIndex && prevProps.controllers === nextProps.controllers;
  },
);

ControllerDots.displayName = "ControllerDots";
