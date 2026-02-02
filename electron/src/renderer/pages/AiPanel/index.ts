// Main component
export { default as AiPanel } from './AiPanel';

// Types
export * from './types';

// Components
export { VoiceBubble } from './components/VoiceBubble';
export { AudioVisualizer } from './components/AudioVisualizer';
export { PanelHeader } from './components/PanelHeader';
export { SwipeContainer } from './components/SwipeContainer';
export { ControllerDots } from './components/ControllerDots';
export { ExpansionArea } from './components/ExpansionArea';

// Controller registry
export {
  registerController,
  unregisterController,
  getControllers,
  getController,
  hasController,
} from './controllers';

// Default controller plugins
export {
  basicControlsPlugin,
  musicPlayerPlugin,
  appLauncherPlugin,
  webSearchPlugin,
} from './controllers';
