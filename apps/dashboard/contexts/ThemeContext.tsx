import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useMemo,
  ReactNode,
} from "react";
import logger from "../utils/logger";
// NOTE: Theme is now LOCAL-ONLY (per-device) - no Firestore sync
// This prevents theme changes on one device affecting other devices

export interface ThemeColors {
  primary: string; // Gradient start (e.g., purple-500)
  accent: string; // Gradient end / highlights (e.g., pink-500)
  primaryHex: string; // Hex for custom
  accentHex: string; // Hex for custom
}

export interface Theme {
  id: string;
  name: string;
  colors: ThemeColors;
  isCustom?: boolean;
  isPro?: boolean;
}

export const PRESET_THEMES: Theme[] = [
  {
    id: "default",
    name: "Default",
    colors: {
      primary: "zinc-200",
      accent: "zinc-400",
      primaryHex: "#a1a1aa",
      accentHex: "#71717a",
    },
  },
  {
    id: "emerald",
    name: "Emerald",
    colors: {
      primary: "emerald-500",
      accent: "teal-400",
      primaryHex: "#10b981",
      accentHex: "#2dd4bf",
    },
  },
  {
    id: "violet",
    name: "Violet",
    colors: {
      primary: "violet-600",
      accent: "fuchsia-500",
      primaryHex: "#7c3aed",
      accentHex: "#d946ef",
    },
  },
  {
    id: "rose",
    name: "Rose",
    colors: {
      primary: "rose-500",
      accent: "orange-400",
      primaryHex: "#f43f5e",
      accentHex: "#fb923c",
    },
  },
  {
    id: "amber",
    name: "Amber",
    colors: {
      primary: "amber-500",
      accent: "orange-400",
      primaryHex: "#f59e0b",
      accentHex: "#fb923c",
    },
  },
  {
    id: "cyan",
    name: "Cyan",
    colors: {
      primary: "cyan-500",
      accent: "blue-400",
      primaryHex: "#06b6d4",
      accentHex: "#60a5fa",
    },
  },
  {
    id: "platinum",
    name: "Platinum",
    colors: {
      primary: "slate-300",
      accent: "sky-200",
      primaryHex: "#cbd5e1",
      accentHex: "#bae6fd",
    },
  },
  {
    id: "ocean",
    name: "Ocean",
    colors: {
      primary: "blue-500",
      accent: "sky-400",
      primaryHex: "#3b82f6",
      accentHex: "#38bdf8",
    },
  },
  {
    id: "sunset",
    name: "Sunset",
    colors: {
      primary: "orange-500",
      accent: "red-400",
      primaryHex: "#f97316",
      accentHex: "#f87171",
    },
  },
  {
    id: "forest",
    name: "Forest",
    colors: {
      primary: "green-600",
      accent: "emerald-400",
      primaryHex: "#16a34a",
      accentHex: "#34d399",
    },
  },
  {
    id: "midnight",
    name: "Midnight",
    colors: {
      primary: "indigo-500",
      accent: "purple-400",
      primaryHex: "#6366f1",
      accentHex: "#c084fc",
    },
  },
  {
    id: "coral",
    name: "Coral",
    colors: {
      primary: "red-400",
      accent: "pink-300",
      primaryHex: "#f87171",
      accentHex: "#f9a8d4",
    },
  },
  {
    id: "arctic",
    name: "Arctic",
    colors: {
      primary: "sky-400",
      accent: "cyan-300",
      primaryHex: "#38bdf8",
      accentHex: "#67e8f9",
    },
  },
];

interface ThemeContextType {
  currentTheme: Theme;
  setTheme: (theme: Theme) => void;
  customTheme: Theme | null;
  setCustomTheme: (colors: { primaryHex: string; accentHex: string }) => void;
  applyCustomTheme: () => void;
  isLoading: boolean;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

const STORAGE_KEY = "threadsdash-theme";

// Read theme from localStorage synchronously to prevent flash
const getInitialTheme = (): Theme => {
  if (typeof window === "undefined") return PRESET_THEMES[0];
  try {
    const storedTheme = localStorage.getItem(STORAGE_KEY);
    if (
      storedTheme &&
      storedTheme !== "light" &&
      storedTheme !== "dark" &&
      storedTheme !== "system"
    ) {
      const parsed = JSON.parse(storedTheme);
      if (parsed.isCustom) return parsed;
      const preset = PRESET_THEMES.find((t) => t.id === parsed.id);
      if (preset) return preset;
    }
  } catch {
    // Ignore errors, use default
  }
  return PRESET_THEMES[0];
};

export const ThemeProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const [currentTheme, setCurrentTheme] = useState<Theme>(getInitialTheme);
  const [customTheme, setCustomThemeState] = useState<Theme | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Load theme from localStorage ONLY (per-device, no Firestore sync)
  useEffect(() => {
    const loadTheme = () => {
      try {
        const storedTheme = localStorage.getItem(STORAGE_KEY);
        if (storedTheme) {
          // Migration: If stored value is plain string (old theme mode), clear it
          if (
            storedTheme === "light" ||
            storedTheme === "dark" ||
            storedTheme === "system"
          ) {
            localStorage.removeItem(STORAGE_KEY);
            applyThemeToDOM(PRESET_THEMES[0]);
          } else {
            const parsed = JSON.parse(storedTheme);
            if (parsed.isCustom) {
              setCustomThemeState(parsed);
              setCurrentTheme(parsed);
              applyThemeToDOM(parsed);
            } else {
              const preset = PRESET_THEMES.find((t) => t.id === parsed.id);
              if (preset) {
                setCurrentTheme(preset);
                applyThemeToDOM(preset);
              }
            }
          }
        } else {
          // No stored theme - apply default
          applyThemeToDOM(PRESET_THEMES[0]);
        }
      } catch (error) {
        logger.error("Failed to load theme:", error);
        // Clear corrupted data
        localStorage.removeItem(STORAGE_KEY);
        applyThemeToDOM(PRESET_THEMES[0]);
      } finally {
        setIsLoading(false);
      }
    };

    loadTheme();
  }, []);

  // Apply theme CSS variables to DOM
  const applyThemeToDOM = (theme: Theme) => {
    const root = document.documentElement;
    const body = document.body;

    root.style.setProperty("--theme-primary", theme.colors.primaryHex);
    root.style.setProperty("--theme-accent", theme.colors.accentHex);
    // Make Tailwind token variables theme-reactive
    root.style.setProperty("--td-primary", theme.colors.primaryHex);
    root.style.setProperty("--td-accent", theme.colors.accentHex);
    root.style.setProperty("--td-neutral", theme.colors.accentHex);
    root.style.setProperty("--primary-500", theme.colors.primaryHex);

    // Set dynamic accent color variables
    const hexToRgb = (hex: string): string => {
      const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
      return result
        ? `${parseInt(result[1], 16)}, ${parseInt(result[2], 16)}, ${parseInt(result[3], 16)}`
        : "168, 85, 247"; // Default fallback
    };

    const primaryRgb = hexToRgb(theme.colors.primaryHex);
    const accentRgb = hexToRgb(theme.colors.accentHex);
    // RGB triplets for use with rgba() in inline styles
    root.style.setProperty("--td-primary-rgb", primaryRgb);
    root.style.setProperty("--td-accent-rgb", accentRgb);
    // Legacy --accent and --accent-rgb vars (read by design-system.css and index.html)
    root.style.setProperty("--accent", theme.colors.primaryHex);
    root.style.setProperty("--accent-rgb", primaryRgb);

    // Set data attributes for CSS color matching
    root.setAttribute("data-theme-id", theme.id);
    root.setAttribute("data-color", theme.id);
    body.setAttribute("data-color", theme.id);

    // Also add theme class for additional CSS hooks
    root.classList.remove(...PRESET_THEMES.map((t) => `theme-${t.id}`));
    root.classList.add(`theme-${theme.id}`);
  };

  // Save theme to localStorage ONLY (per-device, no Firestore sync)
  const saveTheme = (theme: Theme) => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(theme));
  };

  const setTheme = React.useCallback((theme: Theme) => {
    setCurrentTheme(theme);
    applyThemeToDOM(theme);
    saveTheme(theme);
  }, []);

  const setCustomTheme = React.useCallback((colors: {
    primaryHex: string;
    accentHex: string;
  }) => {
    const custom: Theme = {
      id: "custom",
      name: "My Theme",
      colors: {
        primary: "custom",
        accent: "custom",
        primaryHex: colors.primaryHex,
        accentHex: colors.accentHex,
      },
      isCustom: true,
      isPro: true,
    };
    setCustomThemeState(custom);
    // Don't apply yet - just preview
    applyThemeToDOM(custom);
  }, []);

  const applyCustomTheme = React.useCallback(() => {
    setCustomThemeState((current) => {
      if (current) {
        setCurrentTheme(current);
        saveTheme(current);
      }
      return current;
    });
  }, []);

  const contextValue = useMemo(
    () => ({
      currentTheme,
      setTheme,
      customTheme,
      setCustomTheme,
      applyCustomTheme,
      isLoading,
    }),
    [currentTheme, setTheme, customTheme, setCustomTheme, applyCustomTheme, isLoading],
  );

  return (
    <ThemeContext.Provider value={contextValue}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
};
