const PENDING_INVITE_KEY = 'juno33-pending-invite';

export function readPendingInvite(): string | null {
  try {
    return localStorage.getItem(PENDING_INVITE_KEY);
  } catch {
    return null;
  }
}

export function writePendingInvite(inviteCode: string): void {
  try {
    localStorage.setItem(PENDING_INVITE_KEY, inviteCode);
  } catch {
    // noop
  }
}

export function clearPendingInvite(): void {
  try {
    localStorage.removeItem(PENDING_INVITE_KEY);
  } catch {
    // noop
  }
}
