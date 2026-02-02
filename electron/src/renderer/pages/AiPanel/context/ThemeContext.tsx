
import { createContext, useContext, useMemo } from "react";
import type{ ReactNode } from "react";
import type { ThemePreferences, IUser } from "@shared/user.types";

// Default Blackish Theme
const DEFAULT_THEME: ThemePreferences = {
  backgroundColor: "rgba(15, 10, 40, 0.95)",
  borderColor: "rgba(165, 180, 252, 0.15)", // indigo-300/15
  accentColor: "rgba(165, 180, 252, 1)",     // indigo-300
  accentColorHover: "rgba(165, 180, 252, 0.8)",
  textColorPrimary: "rgba(224, 231, 255, 1)", // indigo-100
  textColorSecondary: "rgba(165, 180, 252, 0.8)", // indigo-200/80
  
  panelBackgroundCollapsed: "rgba(30, 27, 75, 0.85)",
  panelBackgroundExpanded: "#020205",
};

interface ThemeContextType {
  theme: ThemePreferences;
}

const ThemeContext = createContext<ThemeContextType>({
  theme: DEFAULT_THEME,
});

interface ThemeProviderProps {
  userDetails?: IUser | null;
  children: ReactNode;
}

export function ThemeProvider({ userDetails, children }: ThemeProviderProps) {
  const theme = useMemo(() => {
    // If user has valid theme prefs, merge/use them. Otherwise fallback to default.
    if (userDetails?.theme) {
      return { ...DEFAULT_THEME, ...userDetails.theme };
    }
    return DEFAULT_THEME;
  }, [userDetails]);

  // CSS Variables injection for global usage in child components
  const cssVariables = useMemo(() => ({
    "--bg-primary": theme.backgroundColor,
    "--border-color": theme.borderColor,
    "--accent-color": theme.accentColor,
    "--text-primary": theme.textColorPrimary,
    "--text-secondary": theme.textColorSecondary,
    "--panel-bg-collapsed": theme.panelBackgroundCollapsed,
    "--panel-bg-expanded": theme.panelBackgroundExpanded,
  } as React.CSSProperties), [theme]);

  // Helper for applying hex with opacity
  const getRgba = (hex: string, alpha: number) => {
      // Basic implementation or use existing utils if available
      return hex; 
  }

  return (
    <ThemeContext.Provider value={{ theme }}>
      <div style={cssVariables} className="contents">
        {children}
      </div>
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
