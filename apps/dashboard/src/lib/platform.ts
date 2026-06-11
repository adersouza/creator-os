export function isMacLike(): boolean {
  if (typeof navigator === 'undefined') return false;
  const ua = navigator.userAgent || '';
  // biome-ignore lint/suspicious/noExplicitAny: userAgentData is not in navigator types yet
  const platform = (navigator as any).userAgentData?.platform || navigator.platform || '';
  return /Mac|iPhone|iPad|iPod/i.test(platform) || /Mac OS X/i.test(ua);
}

/** Returns ⌘ on macOS, Ctrl on Windows/Linux. */
export function modKeyLabel(): string {
  return isMacLike() ? '⌘' : 'Ctrl';
}
