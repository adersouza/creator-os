/**
 * Haptic Feedback Utility
 * Provides tactile feedback for user interactions on supported devices
 * Respects user's reduced motion preferences
 */

export enum HapticPattern {
  LIGHT = "light",
  MEDIUM = "medium",
  HEAVY = "heavy",
  SUCCESS = "success",
  WARNING = "warning",
  ERROR = "error",
  SELECTION = "selection",
}

// Vibration patterns in milliseconds [vibrate, pause, vibrate, ...]
const PATTERNS: Record<HapticPattern, number | number[]> = {
  [HapticPattern.LIGHT]: 10,
  [HapticPattern.MEDIUM]: 20,
  [HapticPattern.HEAVY]: 30,
  [HapticPattern.SUCCESS]: [10, 50, 10],
  [HapticPattern.WARNING]: [15, 30, 15],
  [HapticPattern.ERROR]: [20, 50, 20, 50, 20],
  [HapticPattern.SELECTION]: 5,
};

/**
 * Check if haptic feedback is supported
 */
export const isHapticsSupported = (): boolean => {
  return typeof navigator !== "undefined" && "vibrate" in navigator;
};

/**
 * Check if user prefers reduced motion
 */
export const prefersReducedMotion = (): boolean => {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
};

/**
 * Trigger haptic feedback
 * @param pattern - Haptic pattern to play
 * @param force - Force haptic even if reduced motion is preferred
 */
export const haptic = (
  pattern: HapticPattern = HapticPattern.LIGHT,
  force: boolean = false,
): void => {
  // Don't vibrate if not supported
  if (!isHapticsSupported()) {
    return;
  }

  // Respect reduced motion preference unless forced
  if (!force && prefersReducedMotion()) {
    return;
  }

  try {
    const vibrationPattern = PATTERNS[pattern];
    navigator.vibrate(vibrationPattern);
  } catch {
    // Silent fail - haptics are nice-to-have, not critical
  }
};

/**
 * Cancel any ongoing vibration
 */
export const cancelHaptic = (): void => {
  if (isHapticsSupported()) {
    navigator.vibrate(0);
  }
};

// Convenience methods for common patterns
export const haptics = {
  light: () => haptic(HapticPattern.LIGHT),
  medium: () => haptic(HapticPattern.MEDIUM),
  heavy: () => haptic(HapticPattern.HEAVY),
  success: () => haptic(HapticPattern.SUCCESS),
  warning: () => haptic(HapticPattern.WARNING),
  error: () => haptic(HapticPattern.ERROR),
  selection: () => haptic(HapticPattern.SELECTION),
  cancel: cancelHaptic,
};

export default haptics;
