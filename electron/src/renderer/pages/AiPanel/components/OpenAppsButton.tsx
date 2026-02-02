
import { Grid, X } from 'lucide-react';
import { useState } from 'react';

export function OpenAppsButton() {
  const [isOpen, setIsOpen] = useState(false);

  // This would ideally open a modal or trigger the app launcher view
  // For now, it's a toggle button as per requirements
  
  return (
    <button
      onClick={() => setIsOpen(!isOpen)}
      className={`
        w-9 h-9 rounded-full flex items-center justify-center
        bg-[var(--accent-color)] bg-opacity-10 border border-[var(--border-color)]
        hover:bg-opacity-20 hover:border-[var(--accent-color)] hover:border-opacity-25
        hover:-translate-y-0.5 active:scale-95
        transition-all duration-200 outline-none
      `}
      aria-label="Open Apps"
    >
      {isOpen ? (
        <X className="w-[18px] h-[18px] text-[var(--text-primary)]" />
      ) : (
        <Grid className="w-[18px] h-[18px] text-[var(--text-primary)]" />
      )}
    </button>
  );
}
