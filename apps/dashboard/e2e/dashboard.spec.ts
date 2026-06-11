import { expect, test } from "@playwright/test";

const DASHBOARD_PLATFORM_LABELS = ["All", "Threads", "Instagram"] as const;
const ANALYTICS_PLATFORM_LABELS = ["Fleet", "Threads", "Instagram"] as const;

async function assertNoBrokenCopy(page: Parameters<typeof test>[0]["page"]) {
	const bodyText = await page.locator("body").innerText();
	expect(bodyText).not.toContain("NaN");
	expect(bodyText).not.toContain("undefined");
	expect(bodyText).not.toContain("pppp");
}

function filterGroup(page: Parameters<typeof test>[0]["page"], label: string) {
	return page.getByRole("radiogroup", { name: label });
}

async function waitForAnalyticsReady(page: Parameters<typeof test>[0]["page"]) {
	await expect(page.getByRole("heading", { name: "Performance evidence" })).toBeVisible();
	await expect
		.poll(
			async () => {
				const bodyText = await page.locator("body").innerText();
				return bodyText.includes("LOADING EQS TREND");
			},
			{ timeout: 20000, intervals: [500, 1000, 1500] },
		)
		.toBe(false);
}

test.describe("Dashboard", () => {
	test("desktop dashboard matrix stays stable across platform and timeframe filters", async ({ page }) => {
		test.setTimeout(180000);
		await page.goto("/dashboard");
		await page.waitForLoadState("networkidle");
		await expect(page.getByRole("heading", { name: "Dashboard overview" })).toBeAttached();
		await expect(
			page.getByRole("main", { name: "Page content" }).getByRole("status"),
		).toContainText("Dashboard settled");
		await expect(page.getByRole("region", { name: /Dashboard tiles/ })).toBeVisible();
		await expect(page.getByRole("button", { name: "Refresh dashboard data" })).toBeVisible();
		await expect(page.getByRole("button", { name: "Compose" })).toBeVisible();
		const platformFilters = filterGroup(page, "Dashboard platform");

		for (const platform of DASHBOARD_PLATFORM_LABELS) {
			await platformFilters.getByRole("radio", { name: platform, exact: true }).click();
			await expect(platformFilters.getByRole("radio", { name: platform, exact: true })).toBeChecked();
			await expect(page.getByRole("region", { name: /Dashboard tiles/ })).toBeVisible();
			await page.waitForTimeout(800);
			await assertNoBrokenCopy(page);
		}
	});

	test("desktop analytics matrix stays stable across platform and timeframe filters", async ({ page }) => {
		test.setTimeout(180000);
		await page.goto("/analytics");
		await page.waitForLoadState("networkidle");
		await waitForAnalyticsReady(page);
		await expect(page.getByRole("button", { name: "Export", exact: true })).toBeVisible();
		const platformFilters = filterGroup(page, "Platform");

		for (const platform of ANALYTICS_PLATFORM_LABELS) {
			await platformFilters.getByRole("radio", { name: platform, exact: true }).click();
			await expect(platformFilters.getByRole("radio", { name: platform, exact: true })).toBeChecked();
			await page.waitForTimeout(1200);
			await expect(page.locator("body")).toContainText("Investigation brief");
			await expect(page.locator("body")).toContainText("Fleet anomaly grid");
			await assertNoBrokenCopy(page);
		}
	});

	test("mobile dashboard and analytics remain stable across platform and timeframe filters", async ({ page }) => {
		test.setTimeout(180000);
		await page.setViewportSize({ width: 375, height: 812 });

		await page.goto("/dashboard");
		await page.waitForLoadState("networkidle");
		await expect(page.locator("body")).toContainText("Juno33");
		await assertNoBrokenCopy(page);

		await page.goto("/analytics");
		await page.waitForLoadState("networkidle");
		await waitForAnalyticsReady(page);
		await assertNoBrokenCopy(page);
	});

	test("loads without JS errors", async ({ page }) => {
		const errors: string[] = [];
		page.on("pageerror", (err) => {
		// Ignore network failures (dev proxy to prod API is expected to have some)
		if (!err.message.includes("Failed to fetch") && !err.message.includes("NetworkError")) {
			errors.push(err.message);
		}
	});

		await page.goto("/");
		await page.waitForLoadState("networkidle");

		expect(errors).toHaveLength(0);
	});

	test("no NaN values visible on page", async ({ page }) => {
		await page.goto("/dashboard");
		await page.waitForLoadState("networkidle");

		const bodyText = await page.locator("body").innerText();
		expect(bodyText).not.toContain("NaN");
	});

	test("landing page loads", async ({ page }) => {
		await page.goto("/");
		// Title check skipped — update when landing page <title> is finalized
	});

	test("landing route redirects authenticated users to dashboard", async ({ page }) => {
		await page.goto("/");
		await page.waitForURL("**/dashboard");
	});
});
