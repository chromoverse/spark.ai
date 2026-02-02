import type { FC, ReactNode } from "react";

// ============================================
// Controller Plugin System Types
// ============================================

/**
 * Props passed to controller panel components
 */
export interface ControllerProps {
  /** Whether the controller is currently active/visible */
  isActive: boolean;
  /** Request to show/hide expansion area */
  setExpansionVisible: (visible: boolean) => void;
  /** Pass data to expansion component */
  setExpansionData: (data: unknown) => void;
}

/**
 * Props passed to expansion components
 */
export interface ExpansionProps {
  /** Whether expansion is currently visible */
  isExpanded: boolean;
  /** Data from the controller */
  data: unknown;
  /** Close the expansion */
  onClose: () => void;
}

/**
 * Controller plugin definition
 */
export interface ControllerPlugin {
  /** Unique identifier */
  id: string;
  /** Display name */
  name: string;
  /** Icon component or emoji */
  icon?: ReactNode;
  /** Main panel component */
  component: FC<ControllerProps>;
  /** Optional expansion component rendered below panel */
  expansionComponent?: FC<ExpansionProps>;
  /** Display order (lower = first) */
  order?: number;
}

/**
 * Controller registration config
 */
export interface ControllerConfig {
  id: string;
  name: string;
  icon?: ReactNode;
  component: FC<ControllerProps>;
  expansionComponent?: FC<ExpansionProps>;
  order?: number;
}

// ============================================
// Component Props
// ============================================

export interface VoiceBubbleProps {
  audioLevel: number;
}

export interface AudioVisualizerProps {
  audioLevel: number;
}

export interface PanelHeaderProps {
  audioLevel: number;
}

export interface SwipeContainerProps {
  children: ReactNode;
  activeIndex: number;
  totalItems: number;
  onSwipe: (direction: SwipeDirection) => void;
}

export interface ControllerDotsProps {
  controllers: ControllerPlugin[];
  activeIndex: number;
  onSelect: (index: number) => void;
}

export interface ExpansionAreaProps {
  isVisible: boolean;
  children: ReactNode;
  onClose: () => void;
}

// ============================================
// Enums & Utility Types
// ============================================

export type SwipeDirection = "left" | "right";

// ============================================
// App Launcher Types
// ============================================

export interface AppItem {
  id: string;
  name: string;
  icon: string;
  action?: () => void;
}

// ============================================
// Web Search Types
// ============================================

export interface SearchResult {
  title: string;
  url: string;
  favicon?: string;
  snippet?: string;
}

export interface WebSearchData {
  query: string;
  summary?: string;
  results: SearchResult[];
  isLoading: boolean;
}
