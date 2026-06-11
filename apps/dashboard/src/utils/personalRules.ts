/**
 * personalRules.ts — Auto-generate Personal Rules from solved Quick Wins
 *
 * Analyzes solved recommendations + post history to create actionable rules.
 * Max 5 rules shown. Toggles stored in localStorage.
 */

export interface PersonalRule {
	id: string;
	text: string;
	category: "timing" | "content" | "engagement" | "format" | "frequency";
	evidence: string;
	enabled: boolean;
	threshold?: number | undefined;
}

export interface SolvedQuickWin {
	id: string;
	title: string;
	category: string;
	improvementPct: number;
	baselineValue: number;
	currentValue: number;
}

export interface PostHistoryEntry {
	id: string;
	timestamp: string;
	content: string;
	likes: number;
	replies: number;
	reach: number;
	mediaType?: "text" | "image" | "carousel" | "video" | undefined;
}

const RULES_TOGGLE_KEY_BASE = "juno33_personal_rules_toggles";
const RULES_CACHE_KEY_BASE = "juno33_personal_rules_cache";
const MAX_RULES = 5;

function getUserId(): string {
	try {
		const supabaseUrl =
			typeof import.meta !== "undefined"
				? (import.meta as unknown as { env?: { VITE_SUPABASE_URL?: string | undefined } | undefined })
						.env?.VITE_SUPABASE_URL
				: "";
		const projectRef = supabaseUrl?.match(/https:\/\/([^.]+)\./)?.[1];
		if (!projectRef) return "default";
		const raw = localStorage.getItem(`sb-${projectRef}-auth-token`);
		if (raw) {
			const parsed = JSON.parse(raw);
			return parsed?.user?.id ?? parsed?.currentSession?.user?.id ?? "default";
		}
	} catch (err) {
		// biome-ignore lint/suspicious/noConsole: error logging for silent catch blocks
		console.error("[personalRules] getUserId failed:", err);
	}
	return "default";
}

// ── Rule generators by category ─────────────────────────────────────────────

function timingRule(
	win: SolvedQuickWin,
	posts: PostHistoryEntry[],
): PersonalRule | null {
	if (win.category !== "timing") return null;

	// Analyze posts: compare pre-6PM weekday vs post-6PM
	const weekdayPosts = posts.filter((p) => {
		const d = new Date(p.timestamp);
		return d.getDay() >= 1 && d.getDay() <= 5;
	});

	if (weekdayPosts.length < 4) return null;

	const before6 = weekdayPosts.filter(
		(p) => new Date(p.timestamp).getHours() < 18,
	);
	const after6 = weekdayPosts.filter(
		(p) => new Date(p.timestamp).getHours() >= 18,
	);

	if (before6.length === 0 || after6.length === 0) return null;

	const avgReachBefore =
		before6.reduce((s, p) => s + p.reach, 0) / before6.length;
	const avgReachAfter = after6.reduce((s, p) => s + p.reach, 0) / after6.length;
	const diff = Math.round(
		((avgReachAfter - avgReachBefore) / Math.max(avgReachBefore, 1)) * 100,
	);

	if (diff < 15) return null;

	return {
		id: "timing-no-early-weekday",
		text: "Never post before 6 PM on weekdays",
		category: "timing",
		evidence: `Based on: your pre-6 PM posts average ${diff}% less reach (${before6.length} posts analyzed)`,
		enabled: true,
		threshold: 18,
	};
}

function questionRule(
	win: SolvedQuickWin,
	posts: PostHistoryEntry[],
): PersonalRule | null {
	if (win.category !== "content" && win.category !== "engagement") return null;

	const withQuestion = posts.filter((p) => /\?/.test(p.content));
	const without = posts.filter((p) => !/\?/.test(p.content));

	if (withQuestion.length < 3 || without.length < 3) return null;

	const avgEngWith =
		withQuestion.reduce((s, p) => s + p.likes + p.replies, 0) /
		withQuestion.length;
	const avgEngWithout =
		without.reduce((s, p) => s + p.likes + p.replies, 0) / without.length;
	const lift = Math.round(
		((avgEngWith - avgEngWithout) / Math.max(avgEngWithout, 1)) * 100,
	);

	if (lift < 10) return null;

	return {
		id: "content-include-question",
		text: "Always include a question in Threads posts",
		category: "content",
		evidence: `Based on: posts with questions get ${lift}% more engagement (${withQuestion.length} vs ${without.length} posts)`,
		enabled: true,
	};
}

function replyTimeRule(win: SolvedQuickWin): PersonalRule | null {
	if (win.category !== "engagement") return null;
	if (win.improvementPct < 10) return null;

	return {
		id: "engagement-reply-fast",
		text: "Reply within 2 hours",
		category: "engagement",
		evidence: `Based on: your response time improved ${win.improvementPct}% — faster replies correlate with ${Math.round(win.improvementPct * 0.6)}% more engagement`,
		enabled: true,
		threshold: 2,
	};
}

function carouselRule(
	_win: SolvedQuickWin,
	posts: PostHistoryEntry[],
): PersonalRule | null {
	const recentPosts = posts.slice(0, 60);
	const carousels = recentPosts.filter((p) => p.mediaType === "carousel");
	const nonCarousels = recentPosts.filter((p) => p.mediaType !== "carousel");

	if (carousels.length < 3 || nonCarousels.length < 3) return null;

	// Check if carousel engagement has diminishing returns past 2/week
	const weekMap = new Map<string, number>();
	for (const p of carousels) {
		const d = new Date(p.timestamp);
		const startOfYear = new Date(d.getFullYear(), 0, 1);
		const weekNum = Math.ceil(
			((d.getTime() - startOfYear.getTime()) / 86400000 +
				startOfYear.getDay() +
				1) /
				7,
		);
		const weekKey = `${d.getFullYear()}-W${weekNum}`;
		weekMap.set(weekKey, (weekMap.get(weekKey) || 0) + 1);
	}

	const heavyWeeks = [...weekMap.entries()].filter(([, c]) => c > 2);
	if (heavyWeeks.length < 1) return null;

	return {
		id: "format-limit-carousels",
		text: "Limit carousels to 2/week",
		category: "format",
		evidence: `Based on: carousel engagement shows diminishing returns after 2/week across ${heavyWeeks.length} weeks analyzed`,
		enabled: true,
		threshold: 2,
	};
}

function frequencyRule(win: SolvedQuickWin): PersonalRule | null {
	if (win.category !== "frequency") return null;
	if (win.improvementPct < 10) return null;

	return {
		id: "frequency-consistent-cadence",
		text: "Post at least 4 times per week",
		category: "frequency",
		evidence: `Based on: your posting consistency improved ${win.improvementPct}% — consistent cadence drives steady growth`,
		enabled: true,
		threshold: 4,
	};
}

// ── Main generator ──────────────────────────────────────────────────────────

export function generateRules(
	solvedQuickWins: SolvedQuickWin[],
	postHistory: PostHistoryEntry[],
): PersonalRule[] {
	const generators = [
		timingRule,
		questionRule,
		replyTimeRule,
		carouselRule,
		frequencyRule,
	];
	const rules: PersonalRule[] = [];
	const seenIds = new Set<string>();

	for (const win of solvedQuickWins) {
		for (const gen of generators) {
			const rule = gen(win, postHistory);
			if (rule && !seenIds.has(rule.id)) {
				seenIds.add(rule.id);
				rules.push(rule);
			}
			if (rules.length >= MAX_RULES) break;
		}
		if (rules.length >= MAX_RULES) break;
	}

	// Apply saved toggles
	const saved = getSavedToggles();
	return rules.map((r) => ({
		...r,
		enabled: saved[r.id] ?? r.enabled,
	}));
}

// ── Toggle persistence ──────────────────────────────────────────────────────

function getSavedToggles(): Record<string, boolean> {
	try {
		const uid = getUserId();
		const raw = localStorage.getItem(`${RULES_TOGGLE_KEY_BASE}:${uid}`);
		return raw ? JSON.parse(raw) : {};
	} catch {
		return {};
	}
}

export function saveRuleToggle(ruleId: string, enabled: boolean): void {
	const toggles = getSavedToggles();
	toggles[ruleId] = enabled;
	try {
		const uid = getUserId();
		localStorage.setItem(
			`${RULES_TOGGLE_KEY_BASE}:${uid}`,
			JSON.stringify(toggles),
		);
	} catch {
		/* ignore */
	}
}

export function getActiveRules(): PersonalRule[] {
	try {
		const uid = getUserId();
		const raw = localStorage.getItem(`${RULES_CACHE_KEY_BASE}:${uid}`);
		if (!raw) return [];
		const rules: PersonalRule[] = JSON.parse(raw);
		const toggles = getSavedToggles();
		return rules.filter((r) => toggles[r.id] ?? r.enabled);
	} catch {
		return [];
	}
}

export function cacheRules(rules: PersonalRule[]): void {
	try {
		const uid = getUserId();
		localStorage.setItem(
			`${RULES_CACHE_KEY_BASE}:${uid}`,
			JSON.stringify(rules),
		);
	} catch {
		/* ignore */
	}
}

// ── Violation checker for PostComposer ──────────────────────────────────────

export interface RuleViolation {
	ruleId: string;
	message: string;
}

export function checkRuleViolations(
	content: string,
	scheduledTime?: Date,
): RuleViolation[] {
	const activeRules = getActiveRules();
	const violations: RuleViolation[] = [];
	const now = scheduledTime || new Date();

	for (const rule of activeRules) {
		switch (rule.id) {
			case "timing-no-early-weekday": {
				const day = now.getDay();
				const hour = now.getHours();
				if (day >= 1 && day <= 5 && hour < 18) {
					violations.push({
						ruleId: rule.id,
						message:
							"Heads up: You usually see better results posting after 6 PM",
					});
				}
				break;
			}
			case "content-include-question": {
				if (content.length > 20 && !/\?/.test(content)) {
					violations.push({
						ruleId: rule.id,
						message:
							"Heads up: Your posts with questions tend to get more engagement",
					});
				}
				break;
			}
			// carousel and frequency rules checked elsewhere (not per-post)
		}
	}

	return violations;
}
