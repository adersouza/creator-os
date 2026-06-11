import { supabase } from '@/services/supabase';
import { upsertUserSetting, getUserSetting } from '@/services/userSettingsService';

/* Light/dark choice — orthogonal to the brand palette. */
export type ThemeChoice = 'light' | 'dark' | 'system';

function isThemeChoice(v: unknown): v is ThemeChoice {
  return v === 'light' || v === 'dark' || v === 'system';
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

/* Brand palette — orthogonal to light/dark. Juno is canonical (default);
   the Roman-deity alternates each have their own light + dark token sets,
   switched via [data-theme] attribute on <html>. */
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
    await upsertUserSetting(user.id, 'palette', choice);
  } catch {
    /* best-effort — localStorage remains authoritative for unauth users */
  }
}

export async function loadPaletteFromRemote(): Promise<PaletteChoice | null> {
  try {
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return null;
    const value = await getUserSetting(user.id, 'palette');
    return isPaletteChoice(value) ? value : null;
  } catch {
    return null;
  }
}
