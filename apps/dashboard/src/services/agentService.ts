import { z } from 'zod';
import { apiFetch } from '@/lib/apiFetch';
import type { Json } from '@/types/supabase';

export interface AgentActionLogRow {
  id: string;
  session_id: string;
  tool_name: string;
  params_json: Json | null;
  reason: string | null;
  result_summary: string | null;
  success: boolean;
  duration_ms: number | null;
  created_at: string;
}

export interface AgentNoteRow {
  id: string;
  key: string;
  value: string;
  account_group_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentSettings {
  agent_paused: boolean;
}

const agentActionLogRowSchema = z.object({
  id: z.string(),
  session_id: z.string(),
  tool_name: z.string(),
  params_json: z.custom<Json>().nullable(),
  reason: z.string().nullable(),
  result_summary: z.string().nullable(),
  success: z.boolean(),
  duration_ms: z.number().nullable(),
  created_at: z.string(),
});

const agentNoteRowSchema = z.object({
  id: z.string(),
  key: z.string(),
  value: z.string(),
  account_group_id: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

const agentLogResponseSchema = z.object({
  success: z.boolean().optional(),
  actions: z.array(agentActionLogRowSchema).optional().default([]),
});

const agentNotesResponseSchema = z.object({
  success: z.boolean().optional(),
  notes: z.array(agentNoteRowSchema).optional().default([]),
});

const agentSettingsResponseSchema = z.object({
  success: z.boolean().optional(),
  agent_paused: z.boolean().optional().default(false),
});

const okResponseSchema = z.object({
  success: z.boolean().optional(),
});

async function agentFetch<T>(
  action: string,
  schema: z.ZodType<T>,
  options: { method?: string | undefined; bodyJson?: unknown | undefined } = {},
): Promise<T> {
  const fetchOptions: { method?: string; json?: unknown } = {};
  if (options.method !== undefined) fetchOptions.method = options.method;
  if (options.bodyJson !== undefined) fetchOptions.json = options.bodyJson;
  return apiFetch(`/api/agent?action=${encodeURIComponent(action)}`, schema, fetchOptions);
}

export async function fetchAgentLog(limit = 100): Promise<AgentActionLogRow[]> {
  const params = new URLSearchParams({
    action: 'log',
    limit: String(limit),
  });
  const body = await apiFetch(`/api/agent?${params}`, agentLogResponseSchema);
  return body.actions;
}

export async function fetchAgentNotes(): Promise<AgentNoteRow[]> {
  const body = await agentFetch('notes', agentNotesResponseSchema);
  return body.notes;
}

export async function saveAgentNote(key: string, value: string): Promise<void> {
  await agentFetch('notes', okResponseSchema, {
    method: 'POST',
    bodyJson: { action: 'upsert', key, value },
  });
}

export async function deleteAgentNote(key: string): Promise<void> {
  await agentFetch('notes', okResponseSchema, {
    method: 'POST',
    bodyJson: { action: 'delete', key },
  });
}

export async function fetchAgentSettings(): Promise<AgentSettings> {
  const body = await agentFetch('settings', agentSettingsResponseSchema);
  return { agent_paused: body.agent_paused };
}

export async function setAgentPaused(paused: boolean): Promise<AgentSettings> {
  const body = await agentFetch('settings', agentSettingsResponseSchema, {
    method: 'PATCH',
    bodyJson: { agent_paused: paused },
  });
  return { agent_paused: body.agent_paused ?? paused };
}
