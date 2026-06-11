import { supabase } from "@/services/supabase";
import { apiUrl } from "@/lib/apiUrl";

async function authHeaders(): Promise<HeadersInit | null> {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session?.access_token) return null;
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${session.access_token}`,
  };
}

const DIFFS_TTL_MS = 30_000;
const diffsCache = new Map<string, { expiresAt: number; value: PostChannelDiff[] }>();
const diffsInFlight = new Map<string, Promise<PostChannelDiff[]>>();

function invalidateDiffs(draftId?: string | null) {
  if (!draftId) {
    diffsCache.clear();
    diffsInFlight.clear();
    return;
  }
  diffsCache.delete(draftId);
  diffsInFlight.delete(draftId);
}

export interface AccountHealthSignal {
  signal_type:
    | "engagement_spike"
    | "reach_anomaly"
    | "shadowban_risk"
    | "token_expiring"
    | "rate_limit";
  severity: "good" | "warn" | "critical";
}

export interface AccountHealthPill {
  account_id: string;
  signals: AccountHealthSignal[];
}

export async function fetchComposerHealthPills(
  accountIds: string[],
): Promise<AccountHealthPill[]> {
  const headers = await authHeaders();
  if (!headers || accountIds.length === 0) return [];
  const params = new URLSearchParams({
    action: "health-pills",
    account_ids: accountIds.join(","),
  });
  const res = await fetch(apiUrl(`/api/composer?${params}`), { headers });
  if (!res.ok) throw new Error(`Failed to fetch channel health: ${res.status}`);
  const data = await res.json();
  return Array.isArray(data.accounts) ? data.accounts : [];
}

export interface ComposerVariant {
  id: string;
  draft_id: string | null;
  variant_label: "A" | "B" | "C";
  content: string;
  variant_type: string | null;
  predicted_score: number | null;
  predicted_confidence: number | null;
  reasoning_json?: Record<string, unknown> | undefined;
  promoted_at?: string | null | undefined;
}

export interface ComposerCritique {
  score: number;
  predicted_likes: number;
  predicted_replies: number;
  reasoning: Array<{ type: "positive" | "warning" | "tip"; text: string }>;
}

export interface PostChannelDiff {
  id: string;
  draft_id: string;
  platform: string;
  divergence_type: string | null;
  master_caption: string;
  variant_caption: string;
  status: "unresolved" | "accepted" | "reverted";
}

export interface VoiceContextFile {
  account_group_id: string;
  content: string;
  version: number;
  banned_patterns?: string[] | null | undefined;
  audience?: string | null | undefined;
  top_patterns?: unknown[] | undefined;
  last_edited_at?: string | null | undefined;
}

export async function generateComposerVariants(input: {
  caption: string;
  accountId?: string | null | undefined;
  persona?: string | undefined;
  draftId?: string | null | undefined;
}): Promise<ComposerVariant[]> {
  const headers = await authHeaders();
  if (!headers) throw new Error("Not signed in");
  const res = await fetch(apiUrl("/api/composer?action=variants"), {
    method: "POST",
    headers,
    body: JSON.stringify({
      mode: "generate",
      caption: input.caption,
      account_id: input.accountId,
      persona: input.persona,
      draft_id: input.draftId,
      count: 3,
    }),
  });
  if (!res.ok) throw new Error(`Failed to generate variants: ${res.status}`);
  const data = await res.json();
  return Array.isArray(data.variants)
    ? data.variants.map(normalizeVariant)
    : [];
}

export async function promoteComposerVariant(
  id: string,
): Promise<ComposerVariant> {
  const headers = await authHeaders();
  if (!headers) throw new Error("Not signed in");
  const res = await fetch(apiUrl("/api/composer?action=variants"), {
    method: "POST",
    headers,
    body: JSON.stringify({ mode: "promote", id }),
  });
  if (!res.ok) throw new Error(`Failed to promote variant: ${res.status}`);
  const data = await res.json();
  return normalizeVariant(data.variant);
}

export async function critiqueComposerCaption(input: {
  caption: string;
  accountId?: string | null | undefined;
}): Promise<ComposerCritique> {
  const headers = await authHeaders();
  if (!headers) throw new Error("Not signed in");
  const res = await fetch(apiUrl("/api/composer?action=critique"), {
    method: "POST",
    headers,
    body: JSON.stringify({
      caption: input.caption,
      account_id: input.accountId,
    }),
  });
  if (!res.ok) throw new Error(`Failed to critique caption: ${res.status}`);
  return res.json();
}

function normalizeVariant(row: Record<string, unknown>): ComposerVariant {
  return {
    id: String(row.id),
    draft_id: typeof row.draft_id === "string" ? row.draft_id : null,
    variant_label:
      row.variant_label === "B" || row.variant_label === "C"
        ? row.variant_label
        : "A",
    content: String(row.content ?? ""),
    variant_type:
      typeof row.variant_type === "string" ? row.variant_type : null,
    predicted_score:
      typeof row.predicted_score === "number" ? row.predicted_score : null,
    predicted_confidence:
      typeof row.predicted_confidence === "number"
        ? row.predicted_confidence
        : null,
    reasoning_json:
      row.reasoning_json && typeof row.reasoning_json === "object"
        ? (row.reasoning_json as Record<string, unknown>)
        : undefined,
    promoted_at: typeof row.promoted_at === "string" ? row.promoted_at : null,
  };
}

export async function fetchComposerDiffs(
  draftId: string,
): Promise<PostChannelDiff[]> {
  const headers = await authHeaders();
  if (!headers) return [];
  const cached = diffsCache.get(draftId);
  if (cached && cached.expiresAt > Date.now()) return cached.value;
  const existing = diffsInFlight.get(draftId);
  if (existing) return existing;

  const params = new URLSearchParams({ action: "diffs", draft_id: draftId });
  const request = fetch(apiUrl(`/api/composer?${params}`), { headers })
    .then(async (res) => {
      if (!res.ok) throw new Error(`Failed to fetch diffs: ${res.status}`);
      const data = await res.json();
      const diffs = Array.isArray(data.diffs) ? data.diffs : [];
      diffsCache.set(draftId, { expiresAt: Date.now() + DIFFS_TTL_MS, value: diffs });
      return diffs;
    })
    .finally(() => {
      if (diffsInFlight.get(draftId) === request) diffsInFlight.delete(draftId);
    });
  diffsInFlight.set(draftId, request);
  return request;
}

export async function createComposerDiff(input: {
  draftId: string;
  platform: string;
  masterCaption: string;
  variantCaption: string;
}): Promise<PostChannelDiff> {
  const headers = await authHeaders();
  if (!headers) throw new Error("Not signed in");
  const res = await fetch(apiUrl("/api/composer?action=diffs"), {
    method: "POST",
    headers,
    body: JSON.stringify({
      draft_id: input.draftId,
      platform: input.platform,
      master_caption: input.masterCaption,
      variant_caption: input.variantCaption,
    }),
  });
  if (!res.ok) throw new Error(`Failed to create diff: ${res.status}`);
  const data = await res.json();
  invalidateDiffs(input.draftId);
  return data.diff;
}

export async function updateComposerDiff(
  id: string,
  status: "accepted" | "reverted",
): Promise<PostChannelDiff> {
  const headers = await authHeaders();
  if (!headers) throw new Error("Not signed in");
  const res = await fetch(apiUrl("/api/composer?action=diffs"), {
    method: "POST",
    headers,
    body: JSON.stringify({ id, status }),
  });
  if (!res.ok) throw new Error(`Failed to update diff: ${res.status}`);
  const data = await res.json();
  invalidateDiffs(data.diff?.draft_id);
  return data.diff;
}

export async function fetchVoiceContextFile(
  groupId: string,
): Promise<VoiceContextFile> {
  const headers = await authHeaders();
  if (!headers) throw new Error("Not signed in");
  const params = new URLSearchParams({
    action: "voice-file",
    account_group_id: groupId,
  });
  const res = await fetch(apiUrl(`/api/composer?${params}`), { headers });
  if (!res.ok) throw new Error(`Failed to fetch voice file: ${res.status}`);
  const data = await res.json();
  return data.voice_file;
}

export async function saveVoiceContextFile(
  groupId: string,
  content: string,
): Promise<VoiceContextFile> {
  const headers = await authHeaders();
  if (!headers) throw new Error("Not signed in");
  const res = await fetch(apiUrl("/api/composer?action=voice-file"), {
    method: "PUT",
    headers,
    body: JSON.stringify({ account_group_id: groupId, content }),
  });
  if (!res.ok) throw new Error(`Failed to save voice file: ${res.status}`);
  const data = await res.json();
  return data.voice_file;
}

export async function logComposerAiAction(input: {
  accountId?: string | null | undefined;
  actionType: string;
  inputText: string;
  outputText: string;
  latencyMs: number;
  metadata?: Record<string, unknown> | undefined;
}): Promise<void> {
  const headers = await authHeaders();
  if (!headers) return;
  await fetch(apiUrl("/api/composer?action=ai-action-log"), {
    method: "POST",
    headers,
    body: JSON.stringify({
      account_id: input.accountId,
      action_type: input.actionType,
      input_text: input.inputText,
      output_text: input.outputText,
      latency_ms: input.latencyMs,
      metadata: input.metadata ?? {},
    }),
  });
}
