/**
 * PreferencesContext.tsx
 * Global preferences management with localStorage persistence
 * Includes dark/light/system mode toggle that affects entire site
 */

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useMemo,
  ReactNode,
} from "react";
import { logger } from "../utils/logger";
import { Platform } from "../types";

type ThemeMode = "light" | "dark" | "system";

interface Preferences {
  themeMode: ThemeMode; // Replaces darkMode boolean
  compactView: boolean;
  autoRefresh: boolean;
  betaFeatures: boolean;
  timezone: string; // IANA timezone (e.g., "America/New_York") or "auto" for browser detection
  activePlatform: Platform; // "threads" | "instagram"
}

interface PreferencesContextType {
  preferences: Preferences;
  updatePreference: <K extends keyof Preferences>(
    key: K,
    value: Preferences[K],
  ) => Promise<void>;
  isLoading: boolean;
  isDarkMode: boolean; // Computed from themeMode + system preference
  effectiveTheme: "light" | "dark"; // The actual theme being used
  effectiveTimezone: string; // The actual timezone being used (resolved from "auto" or explicit)
}

// Get browser's detected timezone
const getBrowserTimezone = (): string => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return "UTC";
  }
};

const defaultPreferences: Preferences = {
  themeMode: "system", // Default to system
  compactView: false,
  autoRefresh: true,
  betaFeatures: false,
  timezone: "auto", // Default to browser detection
  activePlatform: "threads",
};

const THEME_MODE_KEY = "threadsdash-theme-mode";
const ACTIVE_PLATFORM_KEY = "threadsdash-active-platform";

const PreferencesContext = createContext<PreferencesContextType | undefined>(
  undefined,
);

// Get system dark mode preference
const getSystemDarkMode = (): boolean => {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
};

// Compute effective dark mode based on themeMode
const computeEffectiveTheme = (themeMode: ThemeMode): "light" | "dark" => {
  if (themeMode === "system") {
    return getSystemDarkMode() ? "dark" : "light";
  }
  return themeMode;
};

// Apply theme to DOM
const applyTheme = (theme: "light" | "dark") => {
  const html = document.documentElement;
  const body = document.body;

  html.setAttribute("data-theme", theme);
  body.setAttribute("data-theme", theme);

  if (theme === "dark") {
    html.classList.add("dark");
    html.classList.remove("light");
    body.classList.add("dark");
    body.classList.remove("light");
  } else {
    html.classList.add("light");
    html.classList.remove("dark");
    body.classList.add("light");
    body.classList.remove("dark");
  }

  // Remove hardcoded inline styles — let CSS tokens handle it
  body.style.removeProperty("background-color");
  body.style.removeProperty("color");
};

export const PreferencesProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const [preferences, setPreferences] = useState<Preferences>(() => {
    // Check localStorage for initial theme mode (prevents flash)
    let storedMode: ThemeMode | null = null;
    let storedPlatform: Platform | null = null;
    try {
      storedMode = localStorage.getItem(THEME_MODE_KEY) as ThemeMode | null;
      storedPlatform = localStorage.getItem(ACTIVE_PLATFORM_KEY) as Platform | null;
    } catch {
      // localStorage unavailable (private browsing / restricted environment)
    }
    const initialMode: ThemeMode = storedMode || "system";
    const initialPlatform: Platform = storedPlatform === "instagram" ? "instagram" : "threads";
    return { ...defaultPreferences, themeMode: initialMode, activePlatform: initialPlatform };
  });
  const [isLoading, setIsLoading] = useState(true);
  const [effectiveTheme, setEffectiveTheme] = useState<"light" | "dark">(() =>
    computeEffectiveTheme(preferences.themeMode),
  );

  // Compute effective timezone (resolve "auto" to browser timezone)
  const effectiveTimezone =
    preferences.timezone === "auto"
      ? getBrowserTimezone()
      : preferences.timezone;

  // Update effective theme when preferences change
  const updateEffectiveTheme = React.useCallback((themeMode: ThemeMode) => {
    const newTheme = computeEffectiveTheme(themeMode);
    setEffectiveTheme(newTheme);
    applyTheme(newTheme);
  }, []);

  // Apply theme on initial load
  useEffect(() => {
    updateEffectiveTheme(preferences.themeMode);
  }, []);

  // Listen for system theme changes (only when themeMode is 'system')
  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");

    const handleChange = (e: MediaQueryListEvent) => {
      if (preferences.themeMode === "system") {
        const newTheme = e.matches ? "dark" : "light";
        setEffectiveTheme(newTheme);
        applyTheme(newTheme);
      }
    };

    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, [preferences.themeMode]);

  // Load preferences from localStorage
  useEffect(() => {
    try {
      const storedPrefs = localStorage.getItem("threadsdash-preferences");
      if (storedPrefs) {
        const parsed = JSON.parse(storedPrefs);
        setPreferences((prev) => ({ ...prev, ...parsed }));
        if (parsed.themeMode) {
          updateEffectiveTheme(parsed.themeMode);
        }
      }
    } catch (e) {
      logger.error("Failed to load stored preferences:", e);
    }
    setIsLoading(false);
  }, []);

  // Update a single preference (stable reference via useCallback)
  const updatePreference = React.useCallback(async <K extends keyof Preferences>(
    key: K,
    value: Preferences[K],
  ) => {
    setPreferences((prev) => {
      const newPreferences = { ...prev, [key]: value };

      // Persist to localStorage
      try {
        localStorage.setItem(
          "threadsdash-preferences",
          JSON.stringify(newPreferences),
        );
      } catch { /* ignore */ }

      return newPreferences;
    });

    // Apply theme immediately
    if (key === "themeMode") {
      const themeMode = value as ThemeMode;
      try { localStorage.setItem(THEME_MODE_KEY, themeMode); } catch { /* ignore */ }
      updateEffectiveTheme(themeMode);
    }

    // Persist active platform immediately
    if (key === "activePlatform") {
      try { localStorage.setItem(ACTIVE_PLATFORM_KEY, value as string); } catch { /* ignore */ }
    }

    // Apply compact view immediately
    if (key === "compactView") {
      if (value) {
        document.body.classList.add("compact-view");
      } else {
        document.body.classList.remove("compact-view");
      }
    }
  }, [updateEffectiveTheme]);

  const contextValue = useMemo(
    () => ({
      preferences,
      updatePreference,
      isLoading,
      isDarkMode: effectiveTheme === "dark",
      effectiveTheme,
      effectiveTimezone,
    }),
    [preferences, updatePreference, isLoading, effectiveTheme, effectiveTimezone],
  );

  return (
    <PreferencesContext.Provider value={contextValue}>
      {children}
    </PreferencesContext.Provider>
  );
};

export const usePreferences = () => {
  const context = useContext(PreferencesContext);
  if (context === undefined) {
    throw new Error("usePreferences must be used within a PreferencesProvider");
  }
  return context;
};

// Common timezones for the selector
export const COMMON_TIMEZONES = [
  { value: "auto", label: "Auto-detect (Browser)", group: "Automatic" },
  // Americas
  { value: "America/New_York", label: "Eastern Time (ET)", group: "Americas" },
  { value: "America/Chicago", label: "Central Time (CT)", group: "Americas" },
  { value: "America/Denver", label: "Mountain Time (MT)", group: "Americas" },
  {
    value: "America/Los_Angeles",
    label: "Pacific Time (PT)",
    group: "Americas",
  },
  { value: "America/Anchorage", label: "Alaska Time (AKT)", group: "Americas" },
  { value: "Pacific/Honolulu", label: "Hawaii Time (HST)", group: "Americas" },
  { value: "America/Toronto", label: "Toronto (ET)", group: "Americas" },
  { value: "America/Vancouver", label: "Vancouver (PT)", group: "Americas" },
  {
    value: "America/Mexico_City",
    label: "Mexico City (CST)",
    group: "Americas",
  },
  { value: "America/Sao_Paulo", label: "São Paulo (BRT)", group: "Americas" },
  {
    value: "America/Buenos_Aires",
    label: "Buenos Aires (ART)",
    group: "Americas",
  },
  // Europe
  { value: "Europe/London", label: "London (GMT/BST)", group: "Europe" },
  { value: "Europe/Paris", label: "Paris (CET)", group: "Europe" },
  { value: "Europe/Berlin", label: "Berlin (CET)", group: "Europe" },
  { value: "Europe/Amsterdam", label: "Amsterdam (CET)", group: "Europe" },
  { value: "Europe/Madrid", label: "Madrid (CET)", group: "Europe" },
  { value: "Europe/Rome", label: "Rome (CET)", group: "Europe" },
  { value: "Europe/Zurich", label: "Zurich (CET)", group: "Europe" },
  { value: "Europe/Stockholm", label: "Stockholm (CET)", group: "Europe" },
  { value: "Europe/Moscow", label: "Moscow (MSK)", group: "Europe" },
  // Asia & Pacific
  { value: "Asia/Dubai", label: "Dubai (GST)", group: "Asia & Pacific" },
  { value: "Asia/Kolkata", label: "India (IST)", group: "Asia & Pacific" },
  {
    value: "Asia/Singapore",
    label: "Singapore (SGT)",
    group: "Asia & Pacific",
  },
  {
    value: "Asia/Hong_Kong",
    label: "Hong Kong (HKT)",
    group: "Asia & Pacific",
  },
  { value: "Asia/Shanghai", label: "Shanghai (CST)", group: "Asia & Pacific" },
  { value: "Asia/Tokyo", label: "Tokyo (JST)", group: "Asia & Pacific" },
  { value: "Asia/Seoul", label: "Seoul (KST)", group: "Asia & Pacific" },
  {
    value: "Australia/Sydney",
    label: "Sydney (AEST)",
    group: "Asia & Pacific",
  },
  {
    value: "Australia/Melbourne",
    label: "Melbourne (AEST)",
    group: "Asia & Pacific",
  },
  {
    value: "Pacific/Auckland",
    label: "Auckland (NZST)",
    group: "Asia & Pacific",
  },
  // Other
  { value: "UTC", label: "UTC (Coordinated Universal Time)", group: "Other" },
];
