// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { apiUrl } from '@/lib/apiUrl';
import { supabase } from '@/services/supabase';

/**
 * Reports PDF download client. Hits `/api/reports?action=generateFromReport`
 * on the backend, which looks up the stored report config, aggregates the
 * user's Threads posts over the cadence window, and returns a base64-encoded
 * PDF as `data:application/pdf;base64,...`.
 *
 * This module handles:
 *   - bearer-auth the call using the current Supabase session
 *   - decode the data-URI to a Blob
 *   - trigger a browser download via a transient <a> element
 */

export interface GeneratePdfResult {
  ok: boolean;
  filename?: string | undefined;
  error?: string | undefined;
}

interface BackendPayload {
  pdf?: string | undefined;
  filename?: string | undefined;
}

function dataUriToBlob(dataUri: string): Blob {
  const match = /^data:([^;]+);base64,(.*)$/.exec(dataUri);
  if (!match) throw new Error('Unexpected PDF payload format from server');
  const [, mime, b64] = match;
  const binary = atob(b64!);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], mime ? { type: mime } : {});
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Safari revokes too early if we call this synchronously — the download
  // aborts before the browser resolves the blob URL. Defer to the next tick.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export async function downloadReportPdf(reportId: string): Promise<GeneratePdfResult> {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session?.access_token) return { ok: false, error: 'Not signed in' };

  try {
    const response = await fetch(apiUrl('/api/reports?action=generateFromReport'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${session.access_token}`,
      },
      body: JSON.stringify({ reportId }),
    });

    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { error?: string | undefined };
      return { ok: false, error: body?.error || `HTTP ${response.status}` };
    }

    const body = (await response.json()) as BackendPayload;
    if (!body.pdf) return { ok: false, error: 'Server returned no PDF payload' };

    const blob = dataUriToBlob(body.pdf);
    const filename = body.filename || `juno33-report-${reportId}.pdf`;
    triggerDownload(blob, filename);

    return { ok: true, filename };
  } catch (err) {
    return {
      ok: false,
      error: err instanceof Error ? err.message : 'Network error',
    };
  }
}
