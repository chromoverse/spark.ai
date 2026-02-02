import { Grid3X3, LayoutGrid } from 'lucide-react';
import type { ControllerProps, ExpansionProps, AppItem } from '../types';

// Default apps list
const DEFAULT_APPS: AppItem[] = [
  { id: 'browser', name: 'Browser', icon: '🧭' },
  { id: 'messages', name: 'Messages', icon: '💬' },
  { id: 'notes', name: 'Notes', icon: '📝' },
  { id: 'calendar', name: 'Calendar', icon: '📅' },
  { id: 'music', name: 'Music', icon: '🎵' },
  { id: 'photos', name: 'Photos', icon: '📷' },
  { id: 'settings', name: 'Settings', icon: '⚙️' },
  { id: 'files', name: 'Files', icon: '📁' },
];

// Panel component (compact view)
export function AppLauncher({ isActive, setExpansionVisible }: ControllerProps) {
  if (!isActive) return null;

  const handleClick = () => {
    setExpansionVisible(true);
  };

  return (
    <div className="flex items-center justify-center px-4">
      <button
        onClick={handleClick}
        className="flex items-center gap-2 px-4 py-2 rounded-lg 
                   bg-indigo-300/10 border border-indigo-300/15
                   hover:bg-indigo-300/20 hover:border-indigo-300/25
                   transition-all duration-200"
      >
        <Grid3X3 className="w-4 h-4 text-indigo-200" />
        <span className="text-sm text-indigo-200/80">Open Apps</span>
      </button>
    </div>
  );
}

// Expansion component (full apps grid)
export function AppLauncherExpansion({ isExpanded }: ExpansionProps) {
  if (!isExpanded) return null;

  return (
    <div className="grid grid-cols-4 gap-3">
      {DEFAULT_APPS.map((app) => (
        <button
          key={app.id}
          className="flex flex-col items-center gap-1.5 p-3 rounded-xl
                     bg-transparent hover:bg-indigo-300/10
                     border border-transparent hover:border-indigo-300/15
                     active:scale-95 transition-all duration-200 group"
          onClick={app.action}
        >
          <span className="text-2xl group-hover:scale-110 transition-transform duration-200">
            {app.icon}
          </span>
          <span className="text-[10px] text-indigo-200/70 group-hover:text-indigo-100 transition-colors">
            {app.name}
          </span>
        </button>
      ))}
    </div>
  );
}

// Plugin config
export const appLauncherPlugin = {
  id: 'app-launcher',
  name: 'Apps',
  icon: <LayoutGrid className="w-4 h-4" />,
  component: AppLauncher,
  expansionComponent: AppLauncherExpansion,
  order: 3,
};
