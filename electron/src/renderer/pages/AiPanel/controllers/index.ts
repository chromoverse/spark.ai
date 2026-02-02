import type { ControllerPlugin, ControllerConfig } from '../types';
import { basicControlsPlugin } from './BasicControls';
import { musicPlayerPlugin } from './MusicPlayer';
import { appLauncherPlugin } from './AppLauncher';
import { webSearchPlugin } from './WebSearch';

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

// Register default controllers
registerController(basicControlsPlugin);
registerController(musicPlayerPlugin);
registerController(appLauncherPlugin);
registerController(webSearchPlugin);

// Re-export plugins for direct import
export { basicControlsPlugin } from './BasicControls';
export { musicPlayerPlugin } from './MusicPlayer';
export { appLauncherPlugin } from './AppLauncher';
export { webSearchPlugin } from './WebSearch';
