import { expect, test, type Page, type Route } from "@playwright/test";
import dotenv from "dotenv";
import { createScaleFixture, type ScaleFixture } from "./helpers/scaleFixtures";

dotenv.config({ path: ".env" });

const fixture = createScaleFixture();
const SESSION_TOKEN = "scale-e2e-token";

test.describe("Seeded 200-account operator scale", () => {
	test.beforeEach(async ({ page }) => {
		await installScaleAuth(page, fixture);
		await installScaleRoutes(page, fixture);
	});

	test("dashboard renders 200-account operator health without broken copy", async ({ page }) => {
		const errors = collectRuntimeErrors(page);
		await page.goto("/dashboard");
		await page.waitForLoadState("domcontentloaded");

		await expect(page.getByRole("heading", { name: "Dashboard overview" })).toBeAttached();
		await expect(page.getByText("Ops health").first()).toBeVisible();
		await expect(page.getByText("Fleet capacity").first()).toBeVisible();
		await expect(page.getByText("AI evals").first()).toBeVisible();
		await expect(page.getByText("Unhealthy accounts").first()).toBeVisible();
		await expect(page.getByText("@threads_scale_001").first()).toBeVisible();
		const opsHealthTile = page.locator(".dv2-ops-health-tile");
		await opsHealthTile.getByRole("button", { name: "Next" }).click();
		await expect(opsHealthTile.getByText(/2\/\d+/)).toBeVisible();
		await assertNoBrokenCopy(page);
		expect(errors()).toEqual([]);
	});

	test("reliability center renders SLOs, Meta usage, webhooks, and tokens at scale", async ({ page }) => {
		const errors = collectRuntimeErrors(page);
		await page.goto("/reliability");
		await page.waitForLoadState("domcontentloaded");

		await expect(page.getByRole("heading", { name: "Reliability Center" })).toBeVisible();
		await expect(page.getByText("Scheduled publishing SLO")).toBeVisible();
		await expect(page.getByText("Rate-limit pressure")).toBeVisible();
		await expect(page.getByText("Webhook replay health", { exact: true })).toBeVisible();
		await expect(page.getByText("Accounts that could fail tomorrow")).toBeVisible();
		await expect(page.getByText("8 scheduled posts failed")).toBeVisible();
		await expect(page.getByText("instagram · igPublish")).toBeVisible();
		await assertNoBrokenCopy(page);
		expect(errors()).toEqual([]);
	});

	test("calendar portfolio matrix handles all/group/platform scale filters", async ({ page }) => {
		const operatorRequests: Array<{ action: string | null; body: unknown }> = [];
		await page.route(/^https?:\/\/[^/]+\/api\/operator/, async (route) => {
			const url = new URL(route.request().url());
			const action = url.searchParams.get("action");
			if (action === "snapshot") return fulfillJson(route, fixture.operatorSnapshot);
			if (action === "dry-run") {
				operatorRequests.push({ action, body: route.request().postDataJSON() });
				return fulfillJson(route, { success: true, intentId: "11111111-1111-4111-8111-111111111111" });
			}
			if (action === "request-approval") {
				operatorRequests.push({ action, body: route.request().postDataJSON() });
				return fulfillJson(route, {
					success: true,
					approvalId: "22222222-2222-4222-8222-222222222222",
					intentId: "11111111-1111-4111-8111-111111111111",
				});
			}
			return fulfillJson(route, { success: true });
		});
		await page.goto("/calendar?view=portfolio");
		await page.waitForLoadState("domcontentloaded");

		await expect(page.getByText("Portfolio capacity")).toBeVisible();
		await expect(page.getByText("Account-day matrix for the selected week")).toBeVisible();
		await expect(page.getByText("@threads_scale_001").first()).toBeVisible();
		await expect(page.getByText("@instagram_scale_002").first()).toBeVisible();

		await page.getByRole("radio", { name: /instagram/i }).click();
		await expect(page.getByText("@instagram_scale_002").first()).toBeVisible();

		await page.getByRole("radio", { name: /threads/i }).click();
		await expect(page.getByText("@threads_scale_001").first()).toBeVisible();

		await page.locator('button[title*="Gap"]').first().click();
		await expect(page).toHaveURL(/approval-queue/);
		expect(operatorRequests.map((request) => request.action)).toEqual(["dry-run", "request-approval"]);
		expect(JSON.stringify(operatorRequests)).toContain("trigger_queue_fill");
		await assertNoBrokenCopy(page);
	});

	test("approval queue shows exact previews and edit controls at scale", async ({ page }) => {
		const operatorRequests: Array<{ action: string | null; body: unknown }> = [];
		await page.route(/^https?:\/\/[^/]+\/api\/operator/, async (route) => {
			const url = new URL(route.request().url());
			const action = url.searchParams.get("action");
			operatorRequests.push({ action, body: route.request().method() === "POST" ? route.request().postDataJSON() : null });
			if (action === "revise-approval") {
				return fulfillJson(route, {
					success: true,
					approvalId: "33333333-3333-4333-8333-333333333333",
					intentId: "44444444-4444-4444-8444-444444444444",
					previousApprovalId: "approval-scale-1",
					previousIntentId: "intent-scale-1",
				});
			}
			if (action === "execute") {
				return fulfillJson(route, {
					success: true,
					status: "executed",
					intentId: "intent-scale-7",
					approvalId: "approval-scale-7",
					message: "Approved operator action executed.",
					dispatch: { supported: true, result: { type: "post_scheduled" } },
				});
			}
			return fulfillJson(route, { success: true });
		});
		await page.goto("/approval-queue?status=pending");
		await page.waitForLoadState("domcontentloaded");

		await expect(page.getByRole("heading", { name: "Approval Queue" })).toBeVisible();
		await expect(page.getByText("Exact action approval").first()).toBeVisible();
		await expect(page.getByText("Exact action preview").first()).toBeVisible();
		await expect(page.getByText("Approval history").first()).toBeVisible();
		await expect(page.getByText("Exact intent bound").first()).toBeVisible();
		await expect(page.getByRole("button", { name: "Edit" }).first()).toBeVisible();
		await page.getByRole("button", { name: "Edit" }).first().click();
		await expect(page.getByText("Structured editor").first()).toBeVisible();
		await page.getByLabel("Caption / post text").first().fill("Updated scale approval caption");
		await expect(page.getByText("Edit and resubmit").first()).toBeVisible();
		await expect(page.getByRole("button", { name: /resubmit revised/i }).first()).toBeVisible();
		await page.getByRole("button", { name: /resubmit revised/i }).first().click();
		await expect(page).toHaveURL(/approvalId=33333333-3333-4333-8333-333333333333/);

		await page.goto("/approval-queue?status=all");
		await expect(page.getByText("Dispatch failed").first()).toBeVisible();
		await expect(page.getByText("Scale handler rejected the scheduled media URL").first()).toBeVisible();
		await expect(page.getByRole("button", { name: "Execute" }).first()).toBeVisible();
		await page.getByRole("button", { name: "Execute" }).first().click();
		expect(operatorRequests.map((request) => request.action)).toContain("revise-approval");
		expect(operatorRequests.map((request) => request.action)).toContain("execute");
		await assertNoBrokenCopy(page);
	});

	test("inbox renders mixed-platform aggregation and marks an item done through the API", async ({ page }) => {
		const markReadRequests: unknown[] = [];
		await page.route(/^https?:\/\/[^/]+\/api\/inbox\?action=mark-read/, async (route) => {
			try {
				markReadRequests.push(route.request().postDataJSON());
			} catch {
				markReadRequests.push({});
			}
			await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ success: true }) });
		});

		await page.goto("/inbox");
		await page.waitForLoadState("domcontentloaded");

		await expect(page.getByRole("heading", { name: /inbox/i })).toBeVisible();
		await expect(page.getByRole("radio", { name: /instagram/i })).toBeVisible();
		await expect(page.getByRole("radio", { name: /threads/i })).toBeVisible();
		await expect(page.getByText("Scale inbox message").first()).toBeVisible();

		await page.getByRole("button", { name: /mark conversation done/i }).first().click();
		await expect.poll(() => markReadRequests.length).toBeGreaterThan(0);
		await assertNoBrokenCopy(page);
	});

	test("listening rows expose workflow actions and update durable source workflow", async ({ page }) => {
		const workflowRequests: unknown[] = [];
		await page.route(/^https?:\/\/[^/]+\/api\/operator\?action=source-workflow/, async (route) => {
			workflowRequests.push(route.request().postDataJSON());
			return fulfillJson(route, { success: true, task: { id: "task-listening-scale-1", status: "resolved" } });
		});

		await page.goto("/listening");
		await page.waitForLoadState("domcontentloaded");

		await expect(page.getByRole("heading", { name: "Social listening" })).toBeVisible();
		await expect(page.getByText("Competitor monitoring")).toBeVisible();
		await expect(page.getByText("Trend monitoring")).toBeVisible();
		await expect(page.getByRole("button", { name: "Reply draft" }).first()).toBeVisible();
		await expect(page.getByRole("button", { name: "Note" }).first()).toBeVisible();
		await expect(page.getByRole("button", { name: "Snooze" }).first()).toBeVisible();
		await expect(page.getByRole("button", { name: "Ignore" }).first()).toBeVisible();
		await expect(page.getByRole("button", { name: "Handled" }).first()).toBeVisible();

		await page.locator("section").filter({ hasText: "Competitor monitoring" }).getByRole("button", { name: "Handled" }).first().click();
		await expect.poll(() => workflowRequests.length).toBeGreaterThan(0);
		expect(JSON.stringify(workflowRequests)).toContain("source_id");
		await assertNoBrokenCopy(page);
	});

	test("reports surfaces large delivery failures and readable download errors", async ({ page }) => {
		await page.goto("/reports");
		await page.waitForLoadState("domcontentloaded");

		await expect(page.getByRole("heading", { name: /scheduled reports/i })).toBeVisible();
		await expect(page.getByText("Scale Report 1").first()).toBeVisible();
		await expect(page.getByText(/Delivery failed/i).first()).toBeVisible();

		const downloadResponse = page.waitForResponse((response) =>
			response.url().includes("/api/reports?action=generateFromReport"),
		);
		await page.getByRole("button", { name: "Download PDF", exact: true }).first().click();
		await expect((await downloadResponse).status()).toBe(500);
		await expect(page.getByText(/Could not generate report/i).first()).toBeVisible();
		await expect(page.getByText(/Scale PDF generation failure/i).first()).toBeVisible();

		const retryResponse = page.waitForResponse((response) =>
			response.url().includes("/api/reports?action=send"),
		);
		await page.getByRole("button", { name: "Retry delivery", exact: true }).first().click();
		await expect((await retryResponse).ok()).toBe(true);
		await assertNoBrokenCopy(page);
	});
});

async function installScaleAuth(page: Page, data: ScaleFixture) {
	await page.addInitScript(
		({ user, token, supabaseUrl }) => {
			const expiresAt = Math.floor(Date.now() / 1000) + 60 * 60;
			const session = {
				access_token: token,
				refresh_token: "scale-refresh-token",
				token_type: "bearer",
				expires_in: 3600,
				expires_at: expiresAt,
				user: {
					id: user.id,
					email: user.email,
					aud: "authenticated",
					role: "authenticated",
					created_at: "2026-05-25T00:00:00.000Z",
					updated_at: "2026-05-25T00:00:00.000Z",
					user_metadata: { full_name: "Scale Operator" },
				},
			};
			const value = JSON.stringify(session);
			const keys = ["sb-undefined-auth-token", "sb--auth-token"];
			try {
				const host = new URL(supabaseUrl).host.split(".")[0];
				keys.push(`sb-${host}-auth-token`);
			} catch {
				// The generic keys above cover local test envs without Supabase vars.
			}
			for (const key of keys) window.localStorage.setItem(key, value);
		},
		{ user: data.user, token: SESSION_TOKEN, supabaseUrl: process.env.VITE_SUPABASE_URL ?? "" },
	);
}

async function installScaleRoutes(page: Page, data: ScaleFixture) {
	await page.route(/^https?:\/\/[^/]+\/auth\/v1\//, async (route) => {
		await route.fulfill({
			status: 200,
			contentType: "application/json",
			body: JSON.stringify({
				access_token: SESSION_TOKEN,
				refresh_token: "scale-refresh-token",
				expires_in: 3600,
				token_type: "bearer",
				user: data.user,
			}),
		});
	});
	await page.route(/^https?:\/\/[^/]+\/rest\/v1\/rpc\/get_calendar_week/, (route) =>
		fulfillJson(route, data.calendarWeek),
	);
	await page.route(/^https?:\/\/[^/]+\/rest\/v1\//, (route) => fulfillSupabaseRest(route, data));
	await page.route(/^https?:\/\/[^/]+\/api\//, (route) => fulfillApi(route, data));
}

async function fulfillApi(route: Route, data: ScaleFixture) {
	const url = new URL(route.request().url());
	const action = url.searchParams.get("action");
	const pathname = url.pathname;

	if (pathname.endsWith("/api/operator") && action === "snapshot") {
		return fulfillJson(route, data.operatorSnapshot);
	}
	if (pathname.endsWith("/api/reliability") && action === "slo-summary") {
		return fulfillJson(route, {
			success: true,
			generatedAt: data.operatorSnapshot.generatedAt,
			reliabilitySlo: data.operatorSnapshot.reliabilitySlo,
			metaApiUsage: data.operatorSnapshot.metaApiUsage,
			webhookHealth: data.operatorSnapshot.webhookHealth,
			tokenSlo: data.operatorSnapshot.tokenSlo,
		});
	}
	if (pathname.endsWith("/api/operator") && action === "tasks") {
		return fulfillJson(route, { success: true, tasks: data.operatorSnapshot.tasks ?? [], task: data.operatorSnapshot.tasks?.[0] ?? null });
	}
	if (pathname.endsWith("/api/operator") && action === "source-workflow") {
		return fulfillJson(route, { success: true, task: { id: "task-source-workflow-scale", status: "resolved" } });
	}
	if (pathname.endsWith("/api/operator") && action === "dry-run") {
		return fulfillJson(route, { success: true, intentId: "11111111-1111-4111-8111-111111111111" });
	}
	if (pathname.endsWith("/api/operator") && action === "request-approval") {
		return fulfillJson(route, {
			success: true,
			approvalId: "22222222-2222-4222-8222-222222222222",
			intentId: "11111111-1111-4111-8111-111111111111",
		});
	}
	if (pathname.endsWith("/api/operator") && action === "revise-approval") {
		return fulfillJson(route, {
			success: true,
			approvalId: "33333333-3333-4333-8333-333333333333",
			intentId: "44444444-4444-4444-8444-444444444444",
			previousApprovalId: "approval-scale-1",
			previousIntentId: "intent-scale-1",
		});
	}
	if (pathname.endsWith("/api/operator") && action === "execute") {
		return fulfillJson(route, {
			success: true,
			status: "executed",
			intentId: "intent-scale-7",
			approvalId: "approval-scale-7",
			message: "Approved operator action executed.",
			dispatch: { supported: true, result: { type: "post_scheduled" } },
		});
	}
	if (pathname.endsWith("/api/agent") && action === "approvals") {
		if (route.request().method() === "PATCH") {
			return fulfillJson(route, { success: true, id: "approval-scale-1", status: "rejected", decidedAt: new Date().toISOString() });
		}
		return fulfillJson(route, { success: true, approvals: data.approvals });
	}
	if (pathname.endsWith("/api/inbox") && action === "unified") {
		return fulfillJson(route, {
			success: true,
			messages: data.inboxMessages,
			total: data.inboxMessages.length,
			page: 1,
			limit: 250,
			hasMore: false,
			nextCursor: null,
		});
	}
	if (pathname.endsWith("/api/inbox") && action === "mark-read") {
		return fulfillJson(route, { success: true });
	}
	if (pathname.endsWith("/api/listening") && action === "alerts") {
		return fulfillJson(route, { success: true, alerts: data.listeningAlerts });
	}
	if (pathname.endsWith("/api/reports") && action === "generateFromReport") {
		return route.fulfill({
			status: 500,
			contentType: "application/json",
			body: JSON.stringify({ error: "Scale PDF generation failure" }),
		});
	}
	if (pathname.endsWith("/api/reports") && action === "send") {
		return fulfillJson(route, { success: true, delivered: 1, recipients: 1 });
	}
	if (pathname.endsWith("/api/subscription")) {
		return fulfillJson(route, { tier: "pro", daysRemaining: null, active: true });
	}
	if (pathname.endsWith("/api/push/vapid-key")) {
		return fulfillJson(route, { key: "" });
	}
	if (pathname.endsWith("/api/analytics/feature-usage")) {
		return fulfillJson(route, { ok: true });
	}
	return fulfillJson(route, { success: true });
}

async function fulfillSupabaseRest(route: Route, data: ScaleFixture) {
	const url = new URL(route.request().url());
	const table = url.pathname.split("/rest/v1/")[1]?.split("?")[0] ?? "";
	if (table === "accounts") return fulfillJson(route, data.threadsAccounts);
	if (table === "instagram_accounts") return fulfillJson(route, data.instagramAccounts);
	if (table === "account_groups") return fulfillJson(route, data.groups);
	if (table === "reports") return fulfillJson(route, data.reports);
	if (table === "report_send_log") return fulfillJson(route, data.reportSendLogs);
	if (table === "posts") return fulfillJson(route, data.posts);
	if (table === "listening_results") return fulfillJson(route, data.listeningResults);
	if (table === "competitors") return fulfillJson(route, data.competitors);
	if (table === "competitor_top_posts") return fulfillJson(route, data.competitorPosts);
	if (table === "trend_keywords") return fulfillJson(route, data.trendKeywords);
	if (table === "trend_posts") return fulfillJson(route, data.trendPosts);
	if (table === "user_settings") return fulfillJson(route, []);
	if (table === "profiles") return fulfillJson(route, [{ id: data.user.id, tier: "pro", agent_paused: false }]);
	if (table === "user_workspaces") return fulfillJson(route, [{ id: "scale-workspace" }]);
	if (table === "workspaces") {
		return fulfillJson(route, {
			id: "scale-workspace",
			name: "Scale Workspace",
			owner_id: data.user.id,
			tier: "pro",
			created_at: "2026-05-25T00:00:00.000Z",
			member_count: 1,
			account_count: 200,
			subscription: null,
		});
	}
	if (table === "workspace_members") {
		return fulfillJson(route, [
			{
				workspace_id: "scale-workspace",
				user_id: data.user.id,
				role: "owner",
				joined_at: "2026-05-25T00:00:00.000Z",
				invited_by: data.user.id,
				display_name: "Scale Operator",
				email: data.user.email,
				photo_url: "",
			},
		]);
	}
	if (table === "workspace_activity") return fulfillJson(route, []);
	return fulfillJson(route, []);
}

async function fulfillJson(route: Route, body: unknown) {
	await route.fulfill({
		status: 200,
		contentType: "application/json",
		headers: {
			"access-control-allow-origin": "*",
			"content-range": "0-0/*",
		},
		body: JSON.stringify(body),
	});
}

function collectRuntimeErrors(page: Page) {
	const errors: string[] = [];
	page.on("pageerror", (error) => errors.push(error.message));
	page.on("console", (message) => {
		if (message.type() === "error") errors.push(message.text());
	});
	return () =>
		errors.filter(
			(error) =>
				!error.includes("ResizeObserver loop") &&
				!error.includes("Failed to load resource"),
		);
}

async function assertNoBrokenCopy(page: Page) {
	const bodyText = await page.locator("body").innerText();
	expect(bodyText).not.toContain("NaN");
	expect(bodyText).not.toContain("undefined");
	expect(bodyText).not.toContain("null null");
}
