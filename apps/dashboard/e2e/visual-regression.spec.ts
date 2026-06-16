import { expect, test } from "@playwright/test";

const stories = [
	{
		id: "frontend-quality-shared-patterns--dashboard-stats",
		label: "Views",
		name: "Dashboard stats",
	},
	{
		id: "frontend-quality-shared-patterns--dashboard-stats-dark",
		label: "Scheduled posts",
		name: "Dashboard stats dark",
	},
	{
		id: "frontend-quality-shared-patterns--dense-table",
		label: "The one launch detail everyone misses",
		name: "Dense table",
	},
	{
		id: "frontend-quality-shared-patterns--upload-and-command",
		label: "Drop campaign media",
		name: "Upload and command",
	},
	{
		id: "frontend-quality-shared-patterns--calendar-and-account-detail",
		label: "Calendar event",
		name: "Calendar and account detail",
	},
];

test.describe("Storybook frontend quality smoke", () => {
	for (const story of stories) {
		test(`${story.name} renders`, async ({ page }) => {
			await page.goto(`/iframe.html?id=${story.id}&viewMode=story`);
			await expect(page.locator("#storybook-root")).toContainText(story.label);
			await expect(page.locator("body")).not.toHaveCSS("overflow-x", "scroll");
		});
	}

	test("dashboard stats mobile variant stays within the viewport", async ({ page }) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(
			"/iframe.html?id=frontend-quality-shared-patterns--dashboard-stats&viewMode=story",
		);
		const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
		expect(scrollWidth).toBeLessThanOrEqual(390);
	});
});
