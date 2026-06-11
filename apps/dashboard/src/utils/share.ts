/**
 * Share a URL via the platform's native share sheet when available, falling
 * back to clipboard copy. On iOS/Android + modern Chrome this opens the OS
 * share sheet (WhatsApp, Messages, Mail, AirDrop, etc). On desktop browsers
 * without share() we copy silently so the caller can show a single "Link
 * copied" toast either way.
 *
 * Returns the method actually used so call sites can tune their success
 * message ("Shared" on native, "Link copied" on clipboard).
 */
export async function shareOrCopy(input: {
  url: string;
  title?: string | undefined;
  text?: string | undefined;
}): Promise<'shared' | 'copied' | 'failed'> {
  if (typeof navigator === 'undefined') return 'failed';

  // Feature-detect both share + canShare so we don't crash on Safari <14
  // and don't offer share on browsers that advertise it but reject on call.
  if (
    typeof navigator.share === 'function' &&
    (typeof navigator.canShare !== 'function' || navigator.canShare({ url: input.url }))
  ) {
    try {
	      await navigator.share({
	        url: input.url,
	        ...(input.title ? { title: input.title } : {}),
	        ...(input.text ? { text: input.text } : {}),
	      });
      return 'shared';
    } catch (err) {
      // AbortError = user cancelled the share sheet. Treat as a neutral outcome
      // rather than a failure so the caller doesn't flash an error toast.
      if (err instanceof Error && err.name === 'AbortError') return 'shared';
      // Fall through to clipboard on any other share() failure.
    }
  }

  try {
    await navigator.clipboard.writeText(input.url);
    return 'copied';
  } catch {
    return 'failed';
  }
}
