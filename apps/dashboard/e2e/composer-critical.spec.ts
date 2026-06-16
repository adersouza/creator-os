import { expect, test, type Page } from "@playwright/test";

async function isUnauthenticatedPage(page: Page): Promise<boolean> {
	if (page.url().includes("/login")) return true;
	return page
		.getByText(/sign in to your threads and instagram command center/i)
		.waitFor({ state: "visible", timeout: 1_000 })
		.then(() => true)
		.catch(() => false);
}

async function openComposer(page: Page, targetCount = 1) {
	await page.goto("/composer");
	await page.waitForLoadState("domcontentloaded");
	test.skip(
		await isUnauthenticatedPage(page),
		"No authenticated storage state available",
	);
	await expect(
		page.getByRole("heading", { name: /^(compose|post command center)$/i }),
	).toBeVisible({ timeout: 10_000 });
	const addAccounts = page.getByRole("button", { name: /add accounts/i });
	if (await addAccounts.isVisible().catch(() => false)) {
		await addAccounts.click();
		const accounts = page.locator(".composer-popover button.w-full");
		const available = await accounts.count();
		test.skip(available < targetCount, `Need ${targetCount} publishable accounts in the authenticated state`);
		for (let i = 0; i < targetCount; i += 1) {
			await accounts.nth(i).click();
		}
		const done = page.getByRole("button", { name: /^done$/i }).last();
		if (await done.isVisible().catch(() => false)) {
			await done.click({ timeout: 2_000 }).catch(() => page.keyboard.press("Escape"));
		} else {
			await page.keyboard.press("Escape");
		}
	}
	test.skip(
		await page.getByText(/\[ Targets 0 \]/).isVisible().catch(() => false),
		"No publishable account target available in the authenticated state",
	);
	return page;
}

async function mockPublishJob(
	page: Page,
	finalStatus: "published" | "failed" | Array<"published" | "failed"> = "published",
) {
	const publishRequests: Array<{ prefer: string | null; requestId: string | null }> = [];
	const outcomes = Array.isArray(finalStatus) ? finalStatus : [finalStatus];
	let publishCount = 0;
	const statusPolls = new Map<string, number>();
	await page.route("**/api/posts?action=preflight", (route) =>
		route.fulfill({
			status: 200,
			contentType: "application/json",
			body: JSON.stringify({ ok: true, issues: [], summary: { errors: 0, warnings: 0, infos: 0 } }),
		}),
	);
	await page.route("**/api/posts?action=publish", async (route) => {
		const request = route.request();
		publishCount += 1;
		const jobId = `job-${publishCount}`;
		publishRequests.push({
			prefer: request.headers().prefer ?? null,
			requestId: request.headers()["x-request-id"] ?? null,
		});
		await route.fulfill({
			status: 202,
			headers: { "x-request-id": "server-request-1" },
			contentType: "application/json",
			body: JSON.stringify({ success: true, jobId, status: "queued", stage: "queued", requestId: "server-request-1" }),
		});
	});
	await page.route("**/api/jobs?action=publish-status&id=**", async (route) => {
		const url = new URL(route.request().url());
		const jobId = url.searchParams.get("id") || "job-1";
		const nextCount = (statusPolls.get(jobId) || 0) + 1;
		statusPolls.set(jobId, nextCount);
		const done = nextCount > 1;
		const index = Number(jobId.replace("job-", "")) - 1;
		const outcome = outcomes[index] || outcomes[0] || "published";
		await route.fulfill({
			status: 200,
			contentType: "application/json",
			body: JSON.stringify(
				done && outcome === "published"
					? { success: true, jobId, status: "published", stage: "published", result: { postId: `post-${index + 1}` }, requestId: "server-request-1" }
					: done
						? { success: true, jobId, status: "failed", stage: "failed", errorMessage: "Meta rejected this post", requestId: "server-request-1" }
						: { success: true, jobId, status: "publishing", stage: "publishing", requestId: "server-request-1" },
			),
		});
	});
	return {
		publishRequests,
		getStatusPolls: () =>
			Array.from(statusPolls.values()).reduce((sum, count) => sum + count, 0),
	};
}

test.describe("Composer critical publish reliability", () => {
	test("desktop publish uses async jobs, shows progress, and reaches success", async ({ page }) => {
		const job = await mockPublishJob(page);
		const composer = await openComposer(page);
		await composer.getByRole("textbox", { name: /what's the post/i }).fill("Critical async publish test");
		await composer.getByRole("button", { name: /post to|post now|publish/i }).last().click();

		await expect(page.getByText(/queued for publish|sending to platform|confirming publish/i).first()).toBeVisible({ timeout: 10_000 });
		await expect(page.getByText(/post published|published to/i).first()).toBeVisible({ timeout: 20_000 });
		expect(job.publishRequests[0]?.prefer).toContain("respond-async");
		expect(job.publishRequests[0]?.requestId).toBeTruthy();
		expect(job.getStatusPolls()).toBeGreaterThanOrEqual(1);
	});

	test("desktop publish failure surfaces sanitized error with request id", async ({ page }) => {
		await mockPublishJob(page, "failed");
		const composer = await openComposer(page);
		await composer.getByRole("textbox", { name: /what's the post/i }).fill("Critical async publish failure");
		await composer.getByRole("button", { name: /post to|post now|publish/i }).last().click();

		await expect(page.getByText(/publish failed/i).first()).toBeVisible({ timeout: 20_000 });
		await expect(page.getByText(/request id: server-request-1/i).first()).toBeVisible();
	});

	test("partial multi-account failure keeps the successful publish", async ({ page }) => {
		await mockPublishJob(page, ["published", "failed"]);
		const composer = await openComposer(page, 2);
		await composer.getByRole("textbox", { name: /what's the post/i }).fill("Critical partial publish");
		await composer.getByRole("button", { name: /post to|post now|publish/i }).last().click();

		await expect(page.getByText(/(post published|published to 1 accounts).*1 failed/i).first()).toBeVisible({ timeout: 20_000 });
	});

	test("recovers an in-flight publish job after reload", async ({ page }) => {
		await mockPublishJob(page, "published");
		await page.addInitScript(() => {
			window.localStorage.setItem("juno33.pendingPublishJobs", JSON.stringify(["job-1"]));
		});
		await page.goto("/composer");
		await page.waitForLoadState("domcontentloaded");
		test.skip(
			await isUnauthenticatedPage(page),
			"No authenticated storage state available",
		);

		await expect(page.getByText(/recovered publish completed/i).first()).toBeVisible({ timeout: 20_000 });
	});

	test("mobile publish uses async jobs and reaches success", async ({ page }) => {
		await page.setViewportSize({ width: 375, height: 812 });
		const job = await mockPublishJob(page);
		const composer = await openComposer(page);
		await composer.getByRole("textbox", { name: /what's the post/i }).fill("Critical mobile async publish");
		await composer.getByRole("button", { name: /post to|post now|publish|^post$/i }).last().click();

		await expect(page.getByText(/post published|published to/i).first()).toBeVisible({ timeout: 20_000 });
		expect(job.publishRequests[0]?.prefer).toContain("respond-async");
	});
});
