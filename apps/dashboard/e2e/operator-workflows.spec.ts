import { expect, test } from "@playwright/test";

test.use({ storageState: "e2e/.auth/user.json" });

async function gotoProtected(page: import("@playwright/test").Page, path: string) {
	await page.goto(path);
	await page.waitForLoadState("domcontentloaded");
	test.skip(page.url().includes("/login"), "No authenticated storage state available");
}

test.describe("operator workflow surfaces", () => {
	test("Command-K exposes the analytics ask flow", async ({ page }) => {
		await gotoProtected(page, "/dashboard");

		await page.getByRole("button", { name: /open command palette/i }).click();
		await expect(
			page.getByPlaceholder(/search commands/i),
		).toBeVisible();

		await page.keyboard.type("ask analytics");
		await expect(
			page.getByText(/Ask analytics: ask analytics/i).first(),
		).toBeVisible();
	});

	test("Accounts exposes group management and account controls", async ({ page }) => {
		await gotoProtected(page, "/accounts");

		await expect(page.getByRole("heading", { name: /^Accounts$/ })).toBeVisible();
		await expect(page.getByText(/^Groups$/i)).toBeVisible();
		await expect(page.getByRole("button", { name: /add account/i })).toBeVisible();
		await expect(page.getByRole("textbox", { name: /new group/i })).toBeVisible();
		await expect(page.getByRole("button", { name: /create group/i })).toBeDisabled();
		await expect(page.getByRole("button", { name: /all platforms/i })).toBeVisible();
		await expect(page.getByRole("button", { name: /all statuses/i })).toBeVisible();
	});

	test("Inbox separates Instagram DMs from Threads replies and keeps reply safe", async ({ page }) => {
		await gotoProtected(page, "/inbox");

		await expect(page.getByRole("heading", { name: /inbox/i })).toBeVisible();
		await expect(page.getByRole("radio", { name: /instagram/i })).toBeVisible();
		await expect(page.getByRole("radio", { name: /threads/i })).toBeVisible();

		await page.getByRole("radio", { name: /instagram/i }).click();
		await expect(page.getByRole("tab", { name: /dms/i })).toBeVisible();

		await page.getByRole("radio", { name: /threads/i }).click();
		await expect(page.getByRole("tab", { name: /replies/i })).toBeVisible();
		await expect(page.getByRole("tab", { name: /mentions/i })).toBeVisible();
		await expect(page.getByRole("textbox", { name: /reply or press/i })).toBeVisible();
		await expect(page.getByRole("button", { name: /^Send/i })).toBeDisabled();
	});

	test("Reports supports creation, filtering, and non-destructive actions", async ({ page }) => {
		await gotoProtected(page, "/reports");

		await expect(page.getByRole("heading", { name: /scheduled reports/i })).toBeVisible();
		await expect(page.getByRole("button", { name: /create report/i })).toBeVisible();
		await expect(page.getByPlaceholder("Search reports")).toBeVisible();
		await expect(page.getByRole("button", { name: /copy share link/i }).first()).toBeVisible();
		await expect(page.getByRole("button", { name: /duplicate/i }).first()).toBeVisible();
	});

	test("Content Library upload supports group and creator assignment", async ({ page }) => {
		await gotoProtected(page, "/content-library");

		await expect(page.getByRole("heading", { name: /content library/i })).toBeVisible();
		await page.getByRole("button", { name: /upload media/i }).click();
		await expect(page.getByRole("heading", { name: /upload media/i })).toBeVisible();
		await expect(page.getByRole("button", { name: /drop files here/i })).toBeVisible();
		const uploadDialog = page.getByRole("dialog", { name: /upload media/i });
		await expect(uploadDialog.getByRole("combobox", { name: /group/i })).toBeVisible();
		await expect(uploadDialog.getByRole("combobox", { name: /creator/i })).toBeVisible();
	});

	test("Autopilot exposes queue, replay, conditions, and safe controls", async ({ page }) => {
		await gotoProtected(page, "/autopilot/queue");

		await expect(page.getByRole("heading", { name: /automation control/i })).toBeVisible();
		await expect(page.getByRole("button", { name: /queue/i })).toBeVisible();
		await expect(page.getByRole("button", { name: /replay/i })).toBeVisible();
		await expect(page.getByRole("button", { name: /conditions/i })).toBeVisible();
		await expect(page.getByRole("button", { name: /health/i })).toBeVisible();
	});

	test("Smart Links and Billing render without stale route content", async ({ page }) => {
		await gotoProtected(page, "/links");
		await expect(page.getByRole("heading", { name: /smart links/i })).toBeVisible();
		await expect(page.getByRole("button", { name: /create new link/i })).toBeVisible();

		await page.goto("/billing");
		await expect(page.getByRole("heading", { name: /billing & plans/i })).toBeVisible();
		await expect(page.getByRole("button", { name: /manage in stripe/i })).toBeVisible();
		await expect(page.getByRole("heading", { name: /smart links/i })).toHaveCount(0);
	});
});
