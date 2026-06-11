const STORAGE_PREFIX = 'juno33-onboarding-complete';

function keyForUser(userId: string): string {
  return `${STORAGE_PREFIX}:${userId}`;
}

export function readLocalOnboardingComplete(userId: string | null | undefined): boolean {
  if (!userId) return false;
  try {
    return localStorage.getItem(keyForUser(userId)) === '1';
  } catch {
    return false;
  }
}

export function writeLocalOnboardingComplete(userId: string | null | undefined): void {
  if (!userId) return;
  try {
    localStorage.setItem(keyForUser(userId), '1');
  } catch {
    /* ignore */
  }
}
