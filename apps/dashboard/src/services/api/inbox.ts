import { supabase } from '@/services/supabase';
import { z } from 'zod';
import { apiFetch } from '@/lib/apiFetch';
import type { InboxSuggestion } from '@/components/inbox/types';

const INBOX_META_TTL_MS = 30_000;
const metaCache = new Map<string, { expiresAt: number; value: unknown }>();
const metaInFlight = new Map<string, Promise<unknown>>();

function readCached<T>(key: string): T | null {
  const cached = metaCache.get(key);
  if (!cached || cached.expiresAt < Date.now()) {
    if (cached) metaCache.delete(key);
    return null;
  }
  return cached.value as T;
}

function writeCached<T>(key: string, value: T): T {
  metaCache.set(key, { expiresAt: Date.now() + INBOX_META_TTL_MS, value });
  return value;
}

function cachedMeta<T>(key: string, loader: () => Promise<T>): Promise<T> {
  const cached = readCached<T>(key);
  if (cached) return Promise.resolve(cached);
  const existing = metaInFlight.get(key);
  if (existing) return existing as Promise<T>;
  const request = loader()
    .then((value) => writeCached(key, value))
    .finally(() => {
      if (metaInFlight.get(key) === request) metaInFlight.delete(key);
    });
  metaInFlight.set(key, request);
  return request;
}

function invalidateInboxMeta(prefix?: string) {
  for (const key of metaCache.keys()) {
    if (!prefix || key.startsWith(prefix)) metaCache.delete(key);
  }
  for (const key of metaInFlight.keys()) {
    if (!prefix || key.startsWith(prefix)) metaInFlight.delete(key);
  }
}

async function hasSession(): Promise<boolean> {
	const { data: { session } } = await supabase.auth.getSession();
	return !!session?.access_token;
}

const suggestionRowSchema = z.record(z.string(), z.unknown());
const suggestionsResponseSchema = z.object({
	success: z.boolean().optional(),
	suggestions: z.array(suggestionRowSchema).optional().default([]),
});
const suggestionResponseSchema = z.object({
	success: z.boolean().optional(),
	suggestion: suggestionRowSchema.nullable().optional(),
});
const contradictionResponseSchema = z.object({
	success: z.boolean().optional(),
	contradicts: z.boolean(),
	similarity: z.number(),
	opposing_reply: z.string().nullable(),
});
const okResponseSchema = z.object({
	success: z.boolean().optional(),
});

export async function fetchInboxSuggestions(conversationKey: string): Promise<InboxSuggestion[]> {
  if (!(await hasSession())) return [];
  const params = new URLSearchParams({ action: 'suggestions', conversation_key: conversationKey });
  const data = await apiFetch(`/api/inbox?${params.toString()}`, suggestionsResponseSchema);
  return (data.suggestions ?? []).map(normalizeSuggestion);
}

export async function fetchInboxSuggestionsBatch(conversationKeys: string[]): Promise<InboxSuggestion[]> {
  if (!(await hasSession()) || conversationKeys.length === 0) return [];
  return cachedMeta(`suggestions:${conversationKeys.join('|')}`, async () => {
    const data = await apiFetch('/api/inbox?action=suggestions', suggestionsResponseSchema, {
      method: 'POST',
      json: { conversation_keys: conversationKeys },
    });
    return (data.suggestions ?? []).map(normalizeSuggestion);
  });
}

export async function updateInboxSuggestion(input: {
  id?: string | undefined;
  conversationKey: string;
  status?: 'accepted' | 'rejected' | undefined;
  regenerate?: boolean | undefined;
}): Promise<InboxSuggestion | null> {
  if (!(await hasSession())) throw new Error('Not signed in');
  const data = await apiFetch('/api/inbox?action=suggestions', suggestionResponseSchema, {
    method: 'POST',
    json: {
      id: input.id,
      conversation_key: input.conversationKey,
      status: input.status,
      regenerate: input.regenerate ?? false,
    },
  });
  invalidateInboxMeta('suggestions:');
  return data.suggestion ? normalizeSuggestion(data.suggestion) : null;
}

export async function checkInboxContradiction(input: {
  composerText: string;
  lastReplies: string[];
}): Promise<{ contradicts: boolean; similarity: number; opposing_reply: string | null }> {
  if (!(await hasSession())) return { contradicts: false, similarity: 1, opposing_reply: null };
  const data = await apiFetch('/api/inbox?action=check-contradiction', contradictionResponseSchema, {
    method: 'POST',
    json: {
      composer_text: input.composerText,
      last_replies: input.lastReplies,
    },
  });
  return {
    contradicts: data.contradicts,
    similarity: data.similarity,
    opposing_reply: data.opposing_reply,
  };
}

export async function markInboxRead(input: {
  messageId: string;
  read?: boolean | undefined;
}): Promise<boolean> {
  if (!(await hasSession())) throw new Error('Not signed in');
  await apiFetch('/api/inbox?action=mark-read', okResponseSchema, {
    method: 'POST',
    json: {
      messageId: input.messageId,
      read: input.read ?? true,
    },
  });
  return true;
}

function normalizeSuggestion(row: Record<string, unknown>): InboxSuggestion {
  return {
    id: String(row.id),
    conversation_key: String(row.conversation_key),
    suggestion_text: String(row.suggestion_text ?? ''),
    reasoning: typeof row.reasoning === 'string' ? row.reasoning : null,
    alternatives: Array.isArray(row.alternatives) ? row.alternatives.map(String) : [],
    status: row.status === 'accepted' || row.status === 'rejected' ? row.status : 'pending',
    created_at: typeof row.created_at === 'string' ? row.created_at : undefined,
  };
}
