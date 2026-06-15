import { expect, test } from "@playwright/test";

test.describe("Visual Regression - UI primitives", () => {
	test("StatusPill tone set", async ({ page }) => {
		await page.goto("/iframe.html?id=ui-statuspill--all-tones&viewMode=story");

		const visual = page.getByTestId("status-pill-visual");
		await expect(visual).toBeVisible();
		await expect(visual).toHaveScreenshot("status-pill-all-tones.png", {
			maxDiffPixelRatio: 0.02,
			threshold: 0.1,
		});
	});
});
