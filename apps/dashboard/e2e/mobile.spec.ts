import { expect, test } from "@playwright/test";

// Run against mobile viewports defined in playwright.config.ts
// (mobile-chrome = 393px, mobile-safari = 390px)

test.describe("Mobile viewport", () => {
	test("landing page renders without horizontal overflow", async ({
		page,
	}) => {
		await page.goto("/");
		await page.waitForLoadState("networkidle");

		const bodyWidth = await page.evaluate(
			() => document.body.scrollWidth,
		);
		const viewportWidth = page.viewportSize()?.width ?? 393;
		expect(bodyWidth).toBeLessThanOrEqual(viewportWidth + 1); // 1px tolerance
	});

	test("landing page has no visible horizontal scrollbar", async ({
		page,
	}) => {
		await page.goto("/");
		const hasScrollbar = await page.evaluate(
			() => document.documentElement.scrollWidth > document.documentElement.clientWidth,
		);
		expect(hasScrollbar).toBe(false);
	});

	test("touch targets are at least 44px tall", async ({ page }) => {
		await page.goto("/");
		await page.waitForLoadState("networkidle");

		// Check primary CTA buttons
		const buttons = page.getByRole("link", { name: /get started|sign up/i });
		const count = await buttons.count();
		for (let i = 0; i < Math.min(count, 3); i++) {
			const box = await buttons.nth(i).boundingBox();
			if (box) {
				expect(box.height).toBeGreaterThanOrEqual(44);
			}
		}
	});

	test("nav links are tappable", async ({ page }) => {
		await page.goto("/");
		const nav = page.getByRole("navigation").first();
		await expect(nav).toBeVisible();
	});
});
