import { z } from "zod";
import { apiFetch } from "@/lib/apiFetch";
import { supabase } from "@/services/supabase";

async function hasSession(): Promise<boolean> {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	return !!session?.access_token;
}

const apiKeyRowSchema = z.object({
	id: z.string(),
	name: z.string(),
	key_prefix: z.string(),
	scopes: z.array(z.string()),
	allowed_account_ids: z.array(z.string()).nullable(),
	last_used_at: z.string().nullable().optional().default(null),
	expires_at: z.string().nullable().optional().default(null),
	created_at: z.string().nullable().optional().default(null),
});

const userWebhookRowSchema = z.object({
	id: z.string(),
	url: z.string(),
	events: z.array(z.string()),
	is_active: z.boolean(),
	last_triggered_at: z.string().nullable(),
	created_at: z.string().nullable(),
});

const listApiKeysSchema = z.object({
	success: z.boolean().optional(),
	keys: z.array(apiKeyRowSchema),
});

const createApiKeySchema = z.object({
	success: z.boolean().optional(),
	key: apiKeyRowSchema,
	rawKey: z.string(),
});

const okSchema = z.object({
	success: z.boolean().optional(),
});

const listUserWebhooksSchema = z.object({
	success: z.boolean().optional(),
	webhooks: z.array(userWebhookRowSchema),
});

const createUserWebhookSchema = z.object({
	success: z.boolean().optional(),
	webhook: userWebhookRowSchema,
	secret: z.string(),
});

const testUserWebhookSchema = z.object({
	success: z.boolean().optional(),
	status: z.number(),
	ok: z.boolean(),
});

export interface ApiKeyRow {
	id: string;
	name: string;
	key_prefix: string;
	scopes: string[];
	allowed_account_ids: string[] | null;
	last_used_at: string | null;
	expires_at: string | null;
	created_at: string | null;
}

export async function listApiKeys(): Promise<ApiKeyRow[]> {
	if (!(await hasSession())) return [];
	const data = await apiFetch("/api/developer?action=keys", listApiKeysSchema);
	return data.keys;
}

export async function createApiKey(input: {
	name: string;
	scopes: string[];
	allowed_account_ids?: string[] | null;
}): Promise<{ key: ApiKeyRow; rawKey: string }> {
	if (!(await hasSession())) throw new Error("Not signed in");
	const data = await apiFetch("/api/developer?action=keys", createApiKeySchema, {
		method: "POST",
		json: input,
	});
	return { key: data.key, rawKey: data.rawKey };
}

export async function revokeApiKey(id: string): Promise<void> {
	if (!(await hasSession())) throw new Error("Not signed in");
	await apiFetch(
		`/api/developer?action=keys&id=${encodeURIComponent(id)}`,
		okSchema,
		{ method: "DELETE" },
	);
}

export interface UserWebhookRow {
	id: string;
	url: string;
	events: string[];
	is_active: boolean;
	last_triggered_at: string | null;
	created_at: string | null;
}

export async function listUserWebhooks(): Promise<UserWebhookRow[]> {
	if (!(await hasSession())) return [];
	const data = await apiFetch(
		"/api/settings?action=user-webhooks",
		listUserWebhooksSchema,
	);
	return data.webhooks;
}

export async function createUserWebhook(input: {
	url: string;
	events: string[];
}): Promise<{ webhook: UserWebhookRow; secret: string }> {
	if (!(await hasSession())) throw new Error("Not signed in");
	const data = await apiFetch(
		"/api/settings?action=user-webhooks",
		createUserWebhookSchema,
		{ method: "POST", json: input },
	);
	return { webhook: data.webhook, secret: data.secret };
}

export async function testUserWebhook(
	id: string,
): Promise<{ status: number; ok: boolean }> {
	if (!(await hasSession())) throw new Error("Not signed in");
	const data = await apiFetch(
		"/api/settings?action=user-webhooks",
		testUserWebhookSchema,
		{ method: "POST", json: { mode: "test", id } },
	);
	return { status: data.status, ok: data.ok };
}

export async function deleteUserWebhook(id: string): Promise<void> {
	if (!(await hasSession())) throw new Error("Not signed in");
	await apiFetch("/api/settings?action=user-webhooks", okSchema, {
		method: "DELETE",
		json: { id },
	});
}
