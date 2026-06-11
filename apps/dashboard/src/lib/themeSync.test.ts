import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  persistThemeToRemote,
  loadThemeFromRemote,
  persistPaletteToRemote,
  loadPaletteFromRemote,
} from './themeSync';

const upsertSpy = vi.fn();
const getSpy = vi.fn();

vi.mock('@/services/userSettingsService', () => ({
  upsertUserSetting: (...args: unknown[]) => upsertSpy(...args),
  getUserSetting: (...args: unknown[]) => getSpy(...args),
}));

const mockGetUser = vi.fn();
vi.mock('@/services/supabase', () => ({
  supabase: {
    auth: {
      getUser: () => mockGetUser(),
    },
  },
}));

describe('themeSync — light/dark choice', () => {
  beforeEach(() => {
    upsertSpy.mockReset();
    getSpy.mockReset();
    mockGetUser.mockReset();
  });

  it('persistThemeToRemote no-ops when user is unauthenticated', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });
    await persistThemeToRemote('dark');
    expect(upsertSpy).not.toHaveBeenCalled();
  });

  it('persistThemeToRemote upserts the choice keyed to user id', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'u1' } } });
    await persistThemeToRemote('light');
    expect(upsertSpy).toHaveBeenCalledWith('u1', 'theme', 'light');
  });

  it('persistThemeToRemote swallows errors so localStorage stays authoritative', async () => {
    mockGetUser.mockRejectedValue(new Error('network down'));
    await expect(persistThemeToRemote('system')).resolves.toBeUndefined();
  });

  it('loadThemeFromRemote returns null for unauthenticated user', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });
    expect(await loadThemeFromRemote()).toBeNull();
  });

  it('loadThemeFromRemote returns null for invalid stored value', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'u1' } } });
    getSpy.mockResolvedValue('not-a-theme');
    expect(await loadThemeFromRemote()).toBeNull();
  });

  it.each(['light', 'dark', 'system'] as const)('loadThemeFromRemote validates %s', async (val) => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'u1' } } });
    getSpy.mockResolvedValue(val);
    expect(await loadThemeFromRemote()).toBe(val);
  });
});

describe('themeSync — palette choice', () => {
  beforeEach(() => {
    upsertSpy.mockReset();
    getSpy.mockReset();
    mockGetUser.mockReset();
  });

  it('persistPaletteToRemote upserts to palette key', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'u2' } } });
    await persistPaletteToRemote('neptune');
    expect(upsertSpy).toHaveBeenCalledWith('u2', 'palette', 'neptune');
  });

  it.each(['juno', 'neptune', 'apollo', 'mars', 'diana', 'vulcan', 'minerva'] as const)(
    'loadPaletteFromRemote validates %s',
    async (val) => {
      mockGetUser.mockResolvedValue({ data: { user: { id: 'u2' } } });
      getSpy.mockResolvedValue(val);
      expect(await loadPaletteFromRemote()).toBe(val);
    },
  );

  it('loadPaletteFromRemote rejects unknown palette names', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'u2' } } });
    getSpy.mockResolvedValue('vega');
    expect(await loadPaletteFromRemote()).toBeNull();
  });
});
