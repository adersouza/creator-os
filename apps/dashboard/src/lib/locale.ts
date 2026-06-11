/**
 * Locale resolution. Priority:
 *   1. User's setting in Supabase user_settings.locale (mirrored to localStorage)
 *   2. navigator.language
 *   3. 'en-US' fallback
 *
 * Use getLocale() everywhere that formats dates, numbers, relative time.
 * Never hardcode 'en-US' again.
 */

const STORAGE_KEY = 'juno33-locale';

let cached: string | null = null;

export function getLocale(): string {
  if (cached) return cached;
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      cached = stored;
      return stored;
    }
  } catch {
    /* ignore */
  }
  if (typeof navigator !== 'undefined' && navigator.language) {
    cached = navigator.language;
    return navigator.language;
  }
  cached = 'en-US';
  return 'en-US';
}

export function setLocale(locale: string): void {
  cached = locale;
  try {
    localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    /* ignore */
  }
}

/** Shortcut for currency formatting. Falls back to USD until we have multi-currency billing. */
export function formatCurrency(amount: number, currency = 'USD'): string {
  return new Intl.NumberFormat(getLocale(), { style: 'currency', currency }).format(amount);
}

export function formatDate(date: Date | string | number, options?: Intl.DateTimeFormatOptions): string {
  const d = typeof date === 'string' || typeof date === 'number' ? new Date(date) : date;
  return new Intl.DateTimeFormat(getLocale(), options).format(d);
}

export function formatNumber(n: number, options?: Intl.NumberFormatOptions): string {
  return new Intl.NumberFormat(getLocale(), options).format(n);
}
