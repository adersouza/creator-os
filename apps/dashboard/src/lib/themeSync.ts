import { supabase } from '@/services/supabase';
import { upsertUserSetting, getUserSetting } from '@/services/userSettingsService';

/* Light/dark choice — orthogonal to the brand palette. */
export type ThemeChoice = 'light' | 'dark' | 'system';

function isThemeChoice(v: unknown): v is ThemeChoice {
  return v === 'light' || v === 'dark' || v === 'system';
}

const THEME_STORAGE_KEY = 'juno33-theme';
export const THEME_CHANGE_EVENT = 'juno33:theme-change';

export function readThemeChoiceFromStorage(): ThemeChoice {
  if (typeof window === 'undefined') return 'system';
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemeChoice(stored) ? stored : 'system';
  } catch {
    return 'system';
  }
}

export function resolveThemeChoice(choice: ThemeChoice): 'light' | 'dark' {
  if (choice === 'system') {
    if (typeof window === 'undefined') return 'light';
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  return choice;
}

export function applyThemeChoice(choice: ThemeChoice): 'light' | 'dark' {
  const resolved = resolveThemeChoice(choice);
  if (typeof document === 'undefined') return resolved;

  document.documentElement.classList.toggle('dark', resolved === 'dark');

  try {
    if (choice === 'system') window.localStorage.removeItem(THEME_STORAGE_KEY);
    else window.localStorage.setItem(THEME_STORAGE_KEY, choice);
  } catch {
    /* ignore */
  }

  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, {
      detail: { choice, resolved },
    }));
  }

  return resolved;
}

export async function persistThemeToRemote(choice: ThemeChoice): Promise<void> {
  try {
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return;
    await upsertUserSetting(user.id, 'theme', choice);
  } catch {
    /* best-effort — localStorage remains authoritative for unauth users */
  }
}

export async function loadThemeFromRemote(): Promise<ThemeChoice | null> {
  try {
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return null;
    const value = await getUserSetting(user.id, 'theme');
    return isThemeChoice(value) ? value : null;
  } catch {
    return null;
  }
}

/* Brand palette — legacy-compatible API. The product palette is now locked to
   Nova/zinc + Juno oxblood, so every legacy palette value canonicalizes to
   "juno" and no runtime [data-theme] switching is applied. */
export type PaletteChoice =
  | 'juno'
  | 'neptune'
  | 'apollo'
  | 'mars'
  | 'diana'
  | 'vulcan'
  | 'minerva';

const PALETTE_CHOICES: readonly PaletteChoice[] = [
  'juno',
  'neptune',
  'apollo',
  'mars',
  'diana',
  'vulcan',
  'minerva',
];

function isPaletteChoice(v: unknown): v is PaletteChoice {
  return typeof v === 'string' && (PALETTE_CHOICES as readonly string[]).includes(v);
}

export async function persistPaletteToRemote(choice: PaletteChoice): Promise<void> {
  try {
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return;
    void choice;
    await upsertUserSetting(user.id, 'palette', 'juno');
  } catch {
    /* best-effort — localStorage remains authoritative for unauth users */
  }
}

export async function loadPaletteFromRemote(): Promise<PaletteChoice | null> {
  try {
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return null;
    const value = await getUserSetting(user.id, 'palette');
    return isPaletteChoice(value) ? 'juno' : null;
  } catch {
    return null;
  }
}
