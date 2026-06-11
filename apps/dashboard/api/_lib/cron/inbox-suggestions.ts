import { getUserAIConfig } from "../aiConfig.js";
import { checkAIRateLimit } from "../aiRateLimit.js";
import { generateWithProvider } from "../handlers/auto-post/aiProviders.js";
import { logger } from "../logger.js";
import { getUserTier } from "../tierGate.js";

const MAX_CANDIDATES = 15; // Reduced: 15×~3s LLM = ~45s, fits in 50s budget
const BUDGET_MS = 50_000; // Hard stop 10s before 60s maxDuration

// biome-ignore lint/suspicious/noExplicitAny: new Phase 2/3 tables are not in generated Supabase types until migrations are applied and types regenerated.
type AnyDb = any;

interface InboxCandidate {
	userId: string;
	conversationKey: string;
	platform: "threads" | "instagram";
	type: "dm" | "mention" | "comment";
	accountId: string | null;
	networkId: string | null;
	author: string;
	text: string;
	postContext?: string | null | undefined;
	turns: string[];
	createdAt: string;
}

interface GeneratedSuggestion {
	suggestion_text: string;
	reasoning: string;
	alternatives: string[];
}

const INBOX_REPLY_SCHEMA = {
	type: "object",
	properties: {
		suggestion_text: { type: "string" },
		reasoning: { type: "string" },
		alternatives: {
			type: "array",
			items: { type: "string" },
		},
	},
	required: ["suggestion_text", "reasoning", "alternatives"],
};

export async function runInboxSuggestionsCron(
	db: AnyDb,
): Promise<{ itemsProcessed: number; metadata?: Record<string, unknown> | undefined }> {
	const candidates = await loadRecentCandidates(db);
	let inserted = 0;
	let skipped = 0;
	let failed = 0;
	const budgetStart = Date.now();

	for (const candidate of candidates) {
		if (Date.now() - budgetStart > BUDGET_MS) {
			logger.info("[inbox-suggestions] budget exhausted", { inserted, remaining: candidates.length - inserted - skipped - failed });
			break;
		}
		try {
			const row = await generateAndInsertInboxSuggestion(db, candidate);
			if (row) inserted += 1;
			else skipped += 1;
		} catch (error) {
			failed += 1;
			logger.warn("[inbox-suggestions] candidate failed", {
				conversationKey: candidate.conversationKey,
				error: error instanceof Error ? error.message : String(error),
			});
		}
	}

	return {
		itemsProcessed: inserted,
		metadata: {
			candidates: candidates.length,
			inserted,
			skipped,
			failed,
		},
	};
}

export async function regenerateInboxSuggestion(
	db: AnyDb,
	userId: string,
	conversationKey: string,
) {
	await db
		.from("inbox_ai_suggestions")
		.delete()
		.eq("user_id", userId)
		.eq("conversation_key", conversationKey)
		.eq("status", "pending");

	const candidate = await loadCandidateByKey(db, userId, conversationKey);
	if (!candidate) return null;
	return generateAndInsertInboxSuggestion(db, candidate, true);
}

async function generateAndInsertInboxSuggestion(
	db: AnyDb,
	candidate: InboxCandidate,
	force = false,
) {
	if (!force) {
		const { data: existing } = await db
			.from("inbox_ai_suggestions")
			.select("id")
			.eq("user_id", candidate.userId)
			.eq("conversation_key", candidate.conversationKey)
			.in("status", ["pending", "accepted"])
			.limit(1)
			.maybeSingle();
		if (existing) return null;
	}

	const generated = await generateSuggestion(candidate, await voiceForCandidate(db, candidate));
	if (!generated?.suggestion_text) return null;

	const { data, error } = await db
		.from("inbox_ai_suggestions")
		.insert({
			user_id: candidate.userId,
			conversation_key: candidate.conversationKey,
			suggestion_text: generated.suggestion_text,
			reasoning: generated.reasoning,
			alternatives: generated.alternatives,
			status: "pending",
		})
		.select("id,conversation_key,suggestion_text,reasoning,alternatives,status,created_at")
		.maybeSingle();

	if (error) {
		if (String(error.message).includes("duplicate")) return null;
		throw error;
	}
	return data;
}

async function generateSuggestion(
	candidate: InboxCandidate,
	voiceProfile: string,
): Promise<GeneratedSuggestion | null> {
	const tier = await getUserTier(candidate.userId);
	if (!["pro", "agency", "empire"].includes(tier)) return null;
	const rateLimit = await checkAIRateLimit(candidate.userId, "inbox-suggestions");
	if (!rateLimit.allowed) return null;

	const aiConfig = await getUserAIConfig(candidate.userId);
	if (!aiConfig) return null;

	const prompt = buildPrompt(candidate, voiceProfile);
	const raw = await generateWithProvider(prompt, {
		provider: aiConfig.provider,
		apiKey: aiConfig.apiKey,
		baseUrl: aiConfig.baseUrl,
		model: aiConfig.model,
		ideaCount: 1,
		systemInstruction: "You generate concise social inbox replies. Return JSON only.",
		useStructuredOutput: true,
		structuredOutputSchema: INBOX_REPLY_SCHEMA,
		actionLog: {
			userId: candidate.userId,
			surface: "inbox",
			actionType: "suggestion_generate",
			inputText: prompt,
			metadata: { conversationKey: candidate.conversationKey },
		},
	});
	if (!raw) return null;
	return parseSuggestion(raw);
}

function buildPrompt(candidate: InboxCandidate, voiceProfile: string): string {
	return `INBOX_REPLY_GENERATOR

Voice profile:
${voiceProfile || "Casual, direct, helpful. Keep replies short and human."}

Conversation:
- Platform: ${candidate.platform}
- Type: ${candidate.type}
- From: @${candidate.author}
- Post context: ${candidate.postContext || "None"}
- Last 3 turns:
${candidate.turns.slice(-3).map((turn, i) => `${i + 1}. ${turn}`).join("\n")}

Return a JSON object with:
{
  "suggestion_text": "one concise reply under 220 characters",
  "reasoning": "why this reply fits",
  "alternatives": ["alt draft 1", "alt draft 2", "alt draft 3"]
}`;
}

function parseSuggestion(raw: string): GeneratedSuggestion | null {
	try {
		const cleaned = raw
			.trim()
			.replace(/^```json\s*/i, "")
			.replace(/^```\s*/i, "")
			.replace(/```$/i, "")
			.trim();
		const parsed = JSON.parse(cleaned) as Partial<GeneratedSuggestion>;
		const suggestion = String(parsed.suggestion_text ?? "").trim();
		if (!suggestion) return null;
		return {
			suggestion_text: suggestion,
			reasoning: String(parsed.reasoning ?? "Generated from recent inbox context.").trim(),
			alternatives: Array.isArray(parsed.alternatives)
				? parsed.alternatives.map(String).filter(Boolean).slice(0, 3)
				: [],
		};
	} catch {
		const firstLine = raw.split("\n").find((line) => line.trim())?.trim();
		if (!firstLine) return null;
		return {
			suggestion_text: firstLine,
			reasoning: "Generated from recent inbox context.",
			alternatives: [],
		};
	}
}

async function loadRecentCandidates(db: AnyDb): Promise<InboxCandidate[]> {
	const since = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();
	const out: InboxCandidate[] = [];

	const [threadsReplies, threadsMentions, igComments, igMentions, dms, accounts, igAccounts] =
		await Promise.all([
			db
				.from("post_replies")
				.select("id,content,username,display_name,created_at,posts!inner(user_id,content,account_id)")
				.gte("created_at", since)
				.order("created_at", { ascending: false })
				.limit(MAX_CANDIDATES),
			db
				.from("mentions")
				.select("id,account_id,content,mentioned_by_username,mentioned_at,created_at")
				.gte("created_at", since)
				.order("created_at", { ascending: false })
				.limit(MAX_CANDIDATES),
			db
				.from("ig_comments")
				.select("id,text,username,created_at,posts!inner(user_id,content,instagram_account_id)")
				.gte("created_at", since)
				.order("created_at", { ascending: false })
				.limit(MAX_CANDIDATES),
			db
				.from("ig_mentions")
				.select("id,ig_account_id,caption,username,mentioned_at")
				.gte("mentioned_at", since)
				.order("mentioned_at", { ascending: false })
				.limit(MAX_CANDIDATES),
			db
				.from("inbox_dm_cache")
				.select("id,user_id,account_id,participant_username,conversation_name,last_message_text,last_message_at")
				.gte("last_message_at", since)
				.order("last_message_at", { ascending: false })
				.limit(MAX_CANDIDATES),
			db.from("accounts").select("id,user_id,group_id").eq("is_active", true),
			db.from("instagram_accounts").select("id,user_id,group_id").eq("is_active", true),
		]);

	const accountLookup = new Map<string, { userId: string; groupId: string | null; platform: "threads" | "instagram" }>();
	for (const row of (accounts.data ?? []) as Record<string, unknown>[]) {
		accountLookup.set(String(row.id), {
			userId: String(row.user_id),
			groupId: typeof row.group_id === "string" ? row.group_id : null,
			platform: "threads",
		});
	}
	for (const row of (igAccounts.data ?? []) as Record<string, unknown>[]) {
		accountLookup.set(String(row.id), {
			userId: String(row.user_id),
			groupId: typeof row.group_id === "string" ? row.group_id : null,
			platform: "instagram",
		});
	}

	for (const row of (threadsReplies.data ?? []) as Record<string, unknown>[]) {
		const post = row.posts as { user_id?: string | undefined; content?: string | undefined; account_id?: string | null | undefined } | null;
		out.push({
			userId: String(post?.user_id ?? ""),
			conversationKey: `threads:comment:tr-${row.id}`,
			platform: "threads",
			type: "comment",
			accountId: post?.account_id ?? null,
			networkId: accountLookup.get(String(post?.account_id))?.groupId ?? null,
			author: String(row.display_name || row.username || "unknown"),
			text: String(row.content ?? ""),
			postContext: post?.content ?? null,
			turns: [String(row.content ?? "")],
			createdAt: String(row.created_at ?? new Date().toISOString()),
		});
	}
	for (const row of (threadsMentions.data ?? []) as Record<string, unknown>[]) {
		const accountId = typeof row.account_id === "string" ? row.account_id : null;
		const acct = accountId ? accountLookup.get(accountId) : null;
		out.push({
			userId: acct?.userId ?? "",
			conversationKey: `threads:mention:tm-${row.id}`,
			platform: "threads",
			type: "mention",
			accountId,
			networkId: acct?.groupId ?? null,
			author: String(row.mentioned_by_username || "unknown"),
			text: String(row.content ?? ""),
			turns: [String(row.content ?? "")],
			createdAt: String(row.mentioned_at ?? row.created_at ?? new Date().toISOString()),
		});
	}
	for (const row of (igComments.data ?? []) as Record<string, unknown>[]) {
		const post = row.posts as { user_id?: string | undefined; content?: string | undefined; instagram_account_id?: string | null | undefined } | null;
		out.push({
			userId: String(post?.user_id ?? ""),
			conversationKey: `instagram:comment:ic-${row.id}`,
			platform: "instagram",
			type: "comment",
			accountId: post?.instagram_account_id ?? null,
			networkId: accountLookup.get(String(post?.instagram_account_id))?.groupId ?? null,
			author: String(row.username || "unknown"),
			text: String(row.text ?? ""),
			postContext: post?.content ?? null,
			turns: [String(row.text ?? "")],
			createdAt: String(row.created_at ?? new Date().toISOString()),
		});
	}
	for (const row of (igMentions.data ?? []) as Record<string, unknown>[]) {
		const accountId = typeof row.ig_account_id === "string" ? row.ig_account_id : null;
		const acct = accountId ? accountLookup.get(accountId) : null;
		out.push({
			userId: acct?.userId ?? "",
			conversationKey: `instagram:mention:im-${row.id}`,
			platform: "instagram",
			type: "mention",
			accountId,
			networkId: acct?.groupId ?? null,
			author: String(row.username || "unknown"),
			text: String(row.caption ?? ""),
			turns: [String(row.caption ?? "")],
			createdAt: String(row.mentioned_at ?? new Date().toISOString()),
		});
	}
	for (const row of (dms.data ?? []) as Record<string, unknown>[]) {
		const accountId = typeof row.account_id === "string" ? row.account_id : null;
		const acct = accountId ? accountLookup.get(accountId) : null;
		out.push({
			userId: String(row.user_id || acct?.userId || ""),
			conversationKey: `${acct?.platform ?? "instagram"}:dm:dm-${row.id}`,
			platform: acct?.platform ?? "instagram",
			type: "dm",
			accountId,
			networkId: acct?.groupId ?? null,
			author: String(row.participant_username || row.conversation_name || "unknown"),
			text: String(row.last_message_text ?? ""),
			turns: [String(row.last_message_text ?? "")],
			createdAt: String(row.last_message_at ?? new Date().toISOString()),
		});
	}

	const candidates = out
		.filter((candidate) => candidate.userId && candidate.text.trim())
		.sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
		.slice(0, MAX_CANDIDATES);

	return filterEligibleCandidates(db, candidates);
}

async function loadCandidateByKey(
	db: AnyDb,
	userId: string,
	conversationKey: string,
): Promise<InboxCandidate | null> {
	const candidates = await loadRecentCandidates(db);
	return (
		candidates.find(
			(candidate) =>
				candidate.userId === userId &&
				candidate.conversationKey === conversationKey,
		) ?? null
	);
}

async function filterEligibleCandidates(
	db: AnyDb,
	candidates: InboxCandidate[],
): Promise<InboxCandidate[]> {
	const keys = candidates.map((candidate) => candidate.conversationKey);
	if (keys.length === 0) return [];

	const suggestions = await db
		.from("inbox_ai_suggestions")
		.select("conversation_key,status")
		.in("conversation_key", keys)
		.in("status", ["pending", "accepted"]);

	const activeSuggestion = new Set(
		((suggestions.data ?? []) as Record<string, unknown>[]).map((row) =>
			String(row.conversation_key),
		),
	);

	return candidates.filter(
		(candidate) => !activeSuggestion.has(candidate.conversationKey),
	);
}

async function voiceForCandidate(db: AnyDb, candidate: InboxCandidate): Promise<string> {
	const { data } = await db
		.from("account_groups")
		.select("voice_profile, account_ids")
		.eq("user_id", candidate.userId);
	for (const group of (data ?? []) as Array<{ voice_profile?: unknown | undefined; account_ids?: string[] | null | undefined }>) {
		if (
			candidate.accountId &&
			Array.isArray(group.account_ids) &&
			group.account_ids.includes(candidate.accountId)
		) {
			return normalizeVoiceProfile(group.voice_profile);
		}
	}
	return normalizeVoiceProfile((data ?? [])[0]?.voice_profile);
}

function normalizeVoiceProfile(value: unknown): string {
	if (!value) return "";
	if (typeof value === "string") return value;
	if (typeof value === "object" && "voice_profile" in value) {
		const raw = (value as { voice_profile?: unknown | undefined }).voice_profile;
		return typeof raw === "string" ? raw : JSON.stringify(value);
	}
	return JSON.stringify(value);
}
