import { afterEach, describe, expect, it, } from 'vitest';
import { isMacLike, modKeyLabel } from './platform';

describe('platform', () => {
  const ORIGINAL_PLATFORM = Object.getOwnPropertyDescriptor(navigator, 'platform');
  const ORIGINAL_UA = Object.getOwnPropertyDescriptor(navigator, 'userAgent');

  afterEach(() => {
    if (ORIGINAL_PLATFORM) Object.defineProperty(navigator, 'platform', ORIGINAL_PLATFORM);
    if (ORIGINAL_UA) Object.defineProperty(navigator, 'userAgent', ORIGINAL_UA);
  });

  const stubNavigator = (platform: string, ua: string) => {
    Object.defineProperty(navigator, 'platform', { value: platform, configurable: true });
    Object.defineProperty(navigator, 'userAgent', { value: ua, configurable: true });
  };

  it('recognises macOS via navigator.platform', () => {
    stubNavigator('MacIntel', 'Mozilla/5.0');
    expect(isMacLike()).toBe(true);
    expect(modKeyLabel()).toBe('⌘');
  });

  it('recognises iPhone via navigator.platform', () => {
    stubNavigator('iPhone', 'Mozilla/5.0');
    expect(isMacLike()).toBe(true);
  });

  it('falls back to userAgent for modern browsers that clear platform', () => {
    stubNavigator('', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)');
    expect(isMacLike()).toBe(true);
  });

  it('returns Ctrl for Windows', () => {
    stubNavigator('Win32', 'Mozilla/5.0 (Windows NT 10.0)');
    expect(isMacLike()).toBe(false);
    expect(modKeyLabel()).toBe('Ctrl');
  });

  it('returns Ctrl for Linux', () => {
    stubNavigator('Linux x86_64', 'Mozilla/5.0 (X11; Linux)');
    expect(isMacLike()).toBe(false);
    expect(modKeyLabel()).toBe('Ctrl');
  });
});
