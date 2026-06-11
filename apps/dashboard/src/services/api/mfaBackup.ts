import { supabase } from '@/services/supabase';
import { z } from 'zod';
import { ApiHttpError, apiFetch } from '@/lib/apiFetch';

/**
 * MFA backup codes client. Backend lives at /api/auth/mfa-backup and owns
 * hashing + factor deletion. See its top-of-file comment for protocol notes.
 */

export interface GenerateBackupCodesResult {
  ok: boolean;
  codes?: string[] | undefined;
  error?: string | undefined;
}

export interface VerifyBackupCodeResult {
  ok: boolean;
  unusedRemaining?: number | undefined;
  error?: string | undefined;
}

export interface CountBackupCodesResult {
  ok: boolean;
  unused?: number | undefined;
  error?: string | undefined;
}

async function hasSession(): Promise<boolean> {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return !!session?.access_token;
}

const generateBackupCodesSchema = z.object({
  success: z.boolean().optional(),
  codes: z.array(z.string()).optional().default([]),
});

const verifyBackupCodeSchema = z.object({
  success: z.boolean().optional(),
  ok: z.boolean().optional(),
  unusedRemaining: z.number().optional(),
});

const countBackupCodesSchema = z.object({
  success: z.boolean().optional(),
  unused: z.number().optional().default(0),
});

function errorMessage(err: unknown): string {
  if (err instanceof ApiHttpError) {
    try {
      const body = JSON.parse(err.body) as { error?: unknown | undefined };
      if (typeof body.error === 'string') return body.error;
    } catch {
      /* keep fallback */
    }
    return `HTTP ${err.status}`;
  }
  return err instanceof Error ? err.message : 'Network error';
}

// Shared envelope: translate a nullable Response into a uniform { ok, error }
// shape and hand the parsed JSON body to the caller on success. Every endpoint
// here follows the same contract so the per-endpoint functions only need to
// describe how to shape success responses.
async function callBackupEndpoint<TResponse, TResult>(
  path: string,
  method: 'GET' | 'POST',
  body: unknown,
  schema: z.ZodType<TResponse>,
  parseSuccess: (json: TResponse) => TResult,
): Promise<TResult | { ok: false; error: string }> {
  try {
    if (!(await hasSession())) return { ok: false, error: 'Not signed in' };
    const json = await apiFetch(path, schema, {
      method,
      ...(body !== undefined ? { json: body } : {}),
    });
    return parseSuccess(json);
  } catch (err) {
    return { ok: false, error: errorMessage(err) };
  }
}

export async function generateBackupCodes(): Promise<GenerateBackupCodesResult> {
  return callBackupEndpoint(
    '/api/auth/mfa-backup?action=generate',
    'POST',
    undefined,
    generateBackupCodesSchema,
    (json) => {
      return { ok: true, codes: json.codes };
    },
  );
}

export async function verifyBackupCode(code: string): Promise<VerifyBackupCodeResult> {
  return callBackupEndpoint(
    '/api/auth/mfa-backup?action=verify',
    'POST',
    { code },
    verifyBackupCodeSchema,
    (json) => {
      return {
        ok: true,
        unusedRemaining: json.unusedRemaining,
      };
    },
  );
}

export async function countBackupCodes(): Promise<CountBackupCodesResult> {
  return callBackupEndpoint(
    '/api/auth/mfa-backup?action=count',
    'GET',
    undefined,
    countBackupCodesSchema,
    (json) => {
      return { ok: true, unused: json.unused };
    },
  );
}
