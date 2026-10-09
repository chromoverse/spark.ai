import type { ControllerPlugin, ControllerConfig } from '../types';
import { Gamepad2, Globe, LayoutGrid, Music } from 'lucide-react';
import { BasicControls } from './BasicControls';
import { MusicPlayer } from './MusicPlayer';
import { AppLauncher, AppLauncherExpansion } from './AppLauncher';
import { WebSearch, WebSearchExpansion } from './WebSearch';

// Controller registry
const controllers: Map<string, ControllerPlugin> = new Map();

/**
 * Register a new controller plugin
 */
export function registerController(config: ControllerConfig): void {
  controllers.set(config.id, {
    id: config.id,
    name: config.name,
    icon: config.icon,
    component: config.component,
    expansionComponent: config.expansionComponent,
    order: config.order ?? 99,
  });
}

/**
 * Unregister a controller by ID
 */
export function unregisterController(id: string): boolean {
  return controllers.delete(id);
}

/**
 * Get all controllers sorted by order
 */
export function getControllers(): ControllerPlugin[] {
  return Array.from(controllers.values()).sort((a, b) => (a.order ?? 99) - (b.order ?? 99));
}

/**
 * Get a specific controller by ID
 */
export function getController(id: string): ControllerPlugin | undefined {
  return controllers.get(id);
}

/**
 * Check if a controller is registered
 */
export function hasController(id: string): boolean {
  return controllers.has(id);
}

// Default controllers. Their configs live here, not in the component files, so those files
// export only components (Fast Refresh).
export const appLauncherPlugin = {
  id: 'app-launcher',
  name: 'Apps',
  icon: <LayoutGrid className="w-4 h-4" />,
  component: AppLauncher,
  expansionComponent: AppLauncherExpansion,
  order: 3,
};
export const basicControlsPlugin = {
  id: 'basic-controls',
  name: 'Controls',
  icon: <Gamepad2 className="w-4 h-4" />,
  component: BasicControls,
  order: 1,
};
export const musicPlayerPlugin = {
  id: 'music-player',
  name: 'Music',
  icon: <Music className="w-4 h-4" />,
  component: MusicPlayer,
  order: 2,
};
export const webSearchPlugin = {
  id: 'web-search',
  name: 'Search',
  icon: <Globe className="w-4 h-4" />,
  component: WebSearch,
  expansionComponent: WebSearchExpansion,
  order: 4,
};

// Register default controllers
registerController(basicControlsPlugin);
registerController(musicPlayerPlugin);
registerController(appLauncherPlugin);
registerController(webSearchPlugin);
