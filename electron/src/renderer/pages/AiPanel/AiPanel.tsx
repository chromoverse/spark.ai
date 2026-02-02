import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { motion } from "motion/react";
import { getControllers } from "./controllers";
import { PanelHeader } from "./components/PanelHeader";
import { SwipeContainer } from "./components/SwipeContainer";
import { ControllerDots } from "./components/ControllerDots";
import { ExpansionArea } from "./components/ExpansionArea";
import { ThemeProvider } from "./context/ThemeContext";
import type { SwipeDirection, ControllerPlugin } from "./types";

// Panel size constants
const COLLAPSED_SIZE = { width: 200, height: 60 };
const EXPANDED_SIZE = { width: 360, height: 180 };
const EXPANSION_HEIGHT = 450;
const EXPANSION_WIDTH = 740;

// Memoized resize function (direct, no internal debounce)
const resizeWindow = (() => {
  let lastWidth = 0;
  let lastHeight = 0;

  return (width: number, height: number) => {
    // Skip if same size
    if (lastWidth === width && lastHeight === height) return;

    lastWidth = width;
    lastHeight = height;

    try {
      window.electronApi?.resizeSecondaryWindow?.(width, height);
    } catch {
      // Silently fail
    }
  };
})();

export default function AiPanel() {
  const [isHovered, setIsHovered] = useState(false);
  // TODO : merge this audio level with real audio input level and also #TODO add the ai audio level
  const [audioLevel, setAudioLevel] = useState(0);
  const [activeIndex, setActiveIndex] = useState(0);
  const [expansionVisible, setExpansionVisible] = useState(false);
  const [expansionData, setExpansionData] = useState<unknown>(null);
  const [isDragMode, setIsDragMode] = useState(false);

  const hoverTimeout = useRef<NodeJS.Timeout | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const expansionRef = useRef<HTMLDivElement>(null);

  // Memoize controllers to prevent re-fetching
  const controllers = useMemo(() => getControllers(), []);

  // Simulate audio level
  useEffect(() => {
    const interval = setInterval(() => {
      setAudioLevel(Math.random() * 100);
    }, 80);
    return () => clearInterval(interval);
  }, []);

  // Listen for click-outside events
  useEffect(() => {
    const cleanup = window.electronApi?.onCloseAiPanelExpansion?.(() => {
      setExpansionVisible(false);
      setExpansionData(null);
    });
    return cleanup;
  }, []);

  // Resize window based on state
  useEffect(() => {
    if (expansionVisible) {
      // EXPAND: Resize IMMEDIATELY so window is big enough for content to grow into
      resizeWindow(
        Math.max(EXPANDED_SIZE.width, EXPANSION_WIDTH),
        EXPANDED_SIZE.height + EXPANSION_HEIGHT,
      );
    } else if (isHovered) {
      // HOVER (Expand from collapsed): Resize IMMEDIATELY
      resizeWindow(EXPANDED_SIZE.width, EXPANDED_SIZE.height);
    } else {
      // COLLAPSE: Resize AFTER delay so content can shrink without clipping
      // Delay matches the CSS transition duration (800ms) plus buffer
      const timer = setTimeout(() => {
        resizeWindow(COLLAPSED_SIZE.width, COLLAPSED_SIZE.height);
      }, 850); // Increased buffer to prevent "zigzag" clipping at the end

      return () => clearTimeout(timer);
    }
  }, [isHovered, expansionVisible]);

  // Check if mouse is over panel - with tolerance for smooth transitions
  const checkMousePosition = useCallback(
    (clientX: number, clientY: number): boolean => {
      // Check panel with small tolerance
      const panelRect = panelRef.current?.getBoundingClientRect();
      if (panelRect) {
        const isOverPanel =
          clientX >= panelRect.left - 5 &&
          clientX <= panelRect.right + 5 &&
          clientY >= panelRect.top - 5 &&
          clientY <= panelRect.bottom + 5;

        if (isOverPanel) return true;
      }

      return false;
    },
    [],
  );

  // Optimized hover handlers
  const handleMouseEnter = useCallback(() => {
    if (hoverTimeout.current) {
      clearTimeout(hoverTimeout.current);
      hoverTimeout.current = null;
    }
    setIsHovered(true);
  }, []);

  const handleMouseLeave = useCallback(() => {
    if (hoverTimeout.current) {
      clearTimeout(hoverTimeout.current);
    }

    // Longer delay for ultra-smooth feel
    hoverTimeout.current = setTimeout(() => {
      setIsHovered(false);
    }, 600);
  }, []);

  // Handle expansion area mouse enter
  const handleExpansionMouseEnter = useCallback(() => {
    if (hoverTimeout.current) {
      clearTimeout(hoverTimeout.current);
      hoverTimeout.current = null;
    }
    setIsHovered(true);
  }, []);

  // Handle expansion area mouse leave
  const handleExpansionMouseLeave = useCallback(() => {
    if (hoverTimeout.current) {
      clearTimeout(hoverTimeout.current);
    }

    hoverTimeout.current = setTimeout(() => {
      setIsHovered(false);
    }, 600);
  }, []);

  // Global mouse tracking with optimized throttling
  useEffect(() => {
    if (!isHovered && !expansionVisible) return;

    let rafId: number | null = null;
    let lastX = 0;
    let lastY = 0;
    let lastCheckTime = 0;

    const handleGlobalMouseMove = (e: MouseEvent) => {
      const now = performance.now();

      // Skip if position hasn't changed much (reduce jitter)
      if (Math.abs(e.clientX - lastX) < 3 && Math.abs(e.clientY - lastY) < 3) {
        return;
      }

      // Throttle to max 60fps
      if (now - lastCheckTime < 16) return;

      lastX = e.clientX;
      lastY = e.clientY;
      lastCheckTime = now;

      if (rafId) cancelAnimationFrame(rafId);

      rafId = requestAnimationFrame(() => {
        const isOver = checkMousePosition(e.clientX, e.clientY);

        if (isOver) {
          // Mouse is over component area
          if (hoverTimeout.current) {
            clearTimeout(hoverTimeout.current);
            hoverTimeout.current = null;
          }
          if (!isHovered) {
            setIsHovered(true);
          }
        } else {
          // Mouse left component area - start collapse timer
          if (!hoverTimeout.current) {
            hoverTimeout.current = setTimeout(() => {
              setIsHovered(false);
            }, 600);
          }
        }
      });
    };

    window.addEventListener("mousemove", handleGlobalMouseMove, {
      passive: true,
    });

    return () => {
      window.removeEventListener("mousemove", handleGlobalMouseMove);
      if (rafId) cancelAnimationFrame(rafId);
    };
  }, [isHovered, expansionVisible, checkMousePosition]);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (hoverTimeout.current) {
        clearTimeout(hoverTimeout.current);
      }
    };
  }, []);

  // Close expansion when clicking outside
  useEffect(() => {
    if (!expansionVisible) return;

    const handleClickOutside = (event: MouseEvent) => {
      const { clientX, clientY } = event;

      // Check if click is inside panel bounds
      const panelRect = panelRef.current?.getBoundingClientRect();
      if (
        panelRect &&
        clientX >= panelRect.left &&
        clientX <= panelRect.right &&
        clientY >= panelRect.top &&
        clientY <= panelRect.bottom
      ) {
        return;
      }

      // Check if click is inside expansion bounds
      const expansionRect = expansionRef.current?.getBoundingClientRect();
      if (
        expansionRect &&
        clientX >= expansionRect.left &&
        clientX <= expansionRect.right &&
        clientY >= expansionRect.top &&
        clientY <= expansionRect.bottom
      ) {
        return;
      }

      // Click is outside both, close expansion
      setExpansionVisible(false);
      setExpansionData(null);
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [expansionVisible]);

  // Memoized swipe handler
  const handleSwipe = useCallback(
    (direction: SwipeDirection) => {
      setActiveIndex((prev) => {
        if (direction === "left") {
          return Math.min(prev + 1, controllers.length - 1);
        }
        return Math.max(prev - 1, 0);
      });
      setExpansionVisible(false);
      setExpansionData(null);
    },
    [controllers.length],
  );

  // Memoized dot select handler
  const handleDotSelect = useCallback((index: number) => {
    setActiveIndex(index);
    setExpansionVisible(false);
    setExpansionData(null);
  }, []);

  // Memoized close expansion handler
  const handleCloseExpansion = useCallback(() => {
    setExpansionVisible(false);
    setExpansionData(null);
  }, []);

  // Memoized active controller
  const activeController = useMemo(
    () => controllers[activeIndex],
    [controllers, activeIndex],
  );

  // Memoized panel class name - ULTRA SMOOTH
  const panelClassName = useMemo(
    () => `
    relative backdrop-blur-2xl
    rounded-2xl border border-white/10
    transition-all duration-[800ms] ease-[cubic-bezier(0.16,1,0.3,1)] select-none overflow-hidden
    ${
      isHovered
        ? "w-[340px] bg-[rgba(10,10,15,0.95)] "
        : "w-[200px] bg-[rgba(18,18,23,0.85)] rounded-2xl"
    }
  `,
    [isHovered],
  );

  // Memoized controller items to prevent re-render
  const controllerItems = useMemo(
    () =>
      controllers.map((controller: ControllerPlugin) => (
        <div
          key={controller.id}
          className="flex-shrink-0 w-[340px] flex items-center justify-center"
        >
          <controller.component
            isActive={controller.id === activeController?.id}
            setExpansionVisible={setExpansionVisible}
            setExpansionData={setExpansionData}
          />
        </div>
      )),
    [controllers, activeController],
  );

  // Turn off drag mode when minimized or expanded
  useEffect(() => {
    if (!isHovered || expansionVisible) {
      setIsDragMode(false);
    }
  }, [isHovered, expansionVisible]);

  return (
    <div className="fixed top-0 left-1/2 -translate-x-1/2 z-1000 flex flex-col items-center">
      {/* Global Style for Drag Mode */}
      {isDragMode && (
        <style>{`
          .drag-active button, .drag-active [role="button"] { -webkit-app-region: no-drag; }
          .drag-active .no-drag-area { -webkit-app-region: no-drag; }
        `}</style>
      )}

      {/* Main Panel */}
      <div
        ref={panelRef}
        className={`${panelClassName} ${isDragMode ? "drag-active cursor-move" : ""}`}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        style={{ WebkitAppRegion: isDragMode ? "drag" : "no-drag" } as any}
      >
        {/* Header - Draggable only when expanded/hovered */}
        <div
          className="relative z-10"
          style={
            {
              WebkitAppRegion:
                isHovered || expansionVisible ? "drag" : "no-drag",
              appRegion: isHovered || expansionVisible ? "drag" : "no-drag",
            } as any
          }
        >
          <PanelHeader audioLevel={audioLevel} />
        </div>

        {/* Controls Area (No Drag) */}
        <motion.div
          className="no-drag-area overflow-hidden"
          initial={{ height: 0, opacity: 0 }}
          animate={{
            height: isHovered ? "auto" : 0,
            opacity: isHovered ? 1 : 0,
            y: isHovered ? 0 : -10,
          }}
          transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
        >
          {/* Swipeable Controllers */}
          <div className="h-[72px]">
            <SwipeContainer
              activeIndex={activeIndex}
              totalItems={controllers.length}
              onSwipe={handleSwipe}
              className="h-full"
            >
              {controllerItems}
            </SwipeContainer>
          </div>

          {/* Dots */}
          <ControllerDots
            controllers={controllers}
            activeIndex={activeIndex}
            onSelect={handleDotSelect}
          />
        </motion.div>
      </div>

      {/* Expansion Area */}
      {activeController?.expansionComponent && (
        <ExpansionArea
          ref={expansionRef}
          isVisible={expansionVisible}
          onClose={handleCloseExpansion}
          onMouseEnter={handleExpansionMouseEnter}
          onMouseLeave={handleExpansionMouseLeave}
        >
          <activeController.expansionComponent
            isExpanded={expansionVisible}
            data={expansionData}
            onClose={handleCloseExpansion}
          />
        </ExpansionArea>
      )}
    </div>
  );
}
