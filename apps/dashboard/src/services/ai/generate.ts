/**
 * AI text generation — thin wrapper around the Juno33 `/api/ai/*`
 * endpoints. Never builds its own Gemini/Claude client; always proxies
 * server-side so the API key never reaches the browser.
 *
 * Rate limiting, tier gating, cost tracking, and server-side response
 * caching all live on the backend. This file just threads the auth header
 * and normalizes the response shape.
 */

import { supabase } from '../supabase.js';

export interface AiGenerateOptions {
  /** Model override. Defaults to the server's choice (gemini-2.5-flash). */
  model?: string | undefined;
  /** Max output tokens. Server clamps so don't panic over unsafe values. */
  maxTokens?: number | undefined;
  /** 0.0 = deterministic, 1.0 = creative. Default server-side. */
  temperature?: number | undefined;
  /** Set true to bypass the server's response cache. Default: cache enabled. */
  noCache?: boolean | undefined;
  /** Tag for server-side usage analytics (audit-log bucket). */
  feature?: string | undefined;
  /** Optional account id — server injects the account's voice profile. */
  accountId?: string | undefined;
  platform?: 'threads' | 'instagram' | undefined;
  /**
   * Flag tone-critical / hero posts. When true AND the backend has an
   * Anthropic key, `resolveProvider` routes to Claude Haiku 4.5 with
   * prompt caching. Silently falls back to the default provider otherwise.
   */
  isHeroPost?: boolean | undefined;
}

export class AiNotConfiguredError extends Error {
  constructor() {
    super('AI is not configured for this workspace.');
    this.name = 'AiNotConfiguredError';
  }
}

export class AiRateLimitedError extends Error {
  constructor() {
    super('AI rate limit exceeded. Try again shortly.');
    this.name = 'AiRateLimitedError';
  }
}

async function authedFetch(path: string, body: unknown): Promise<Response> {
  const { data: { session } } = await supabase.auth.getSession();
  if (!session?.access_token) throw new Error('Not authenticated');
  return fetch(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${session.access_token}`,
    },
    body: JSON.stringify(body),
  });
}

/**
 * Generate text via the backend proxy. Returns the raw completion string
 * or throws a typed error for the caller to handle.
 */
export async function generateAiText(
  prompt: string,
  options: AiGenerateOptions = {},
): Promise<string> {
  const response = await authedFetch('/api/ai?action=generate', {
    prompt,
    model: options.model,
    maxTokens: options.maxTokens,
    temperature: options.temperature,
    noCache: options.noCache,
    responseMimeType: 'text/plain',
    feature: options.feature,
    accountId: options.accountId,
    platform: options.platform,
    isHeroPost: options.isHeroPost,
    variants: 1,
  });

  if (response.status === 503) {
    const body = await response.json().catch(() => ({}));
    if (body?.code === 'NO_API_KEY' || body?.code === 'AI_UNAVAILABLE') {
      throw new AiNotConfiguredError();
    }
  }
  if (response.status === 429) throw new AiRateLimitedError();
  if (!response.ok) {
    let message = `AI request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body?.error) message = String(body.error);
    } catch {
      /* keep default */
    }
    throw new Error(message);
  }

  const body = await response.json();
  // /api/ai/generate returns { text: string, ... } or { variants: [{ text }] }
  if (typeof body?.data?.text === 'string') return body.data.text;
  if (Array.isArray(body?.data?.variants) && body.data.variants[0]?.text) {
    return String(body.data.variants[0].text);
  }
  if (typeof body?.text === 'string') return body.text;
  throw new Error('AI response missing text payload');
}
