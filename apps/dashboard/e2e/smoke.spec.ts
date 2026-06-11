import { expect, test } from "@playwright/test";

/**
 * Smoke tests — run against production (set PLAYWRIGHT_BASE_URL=https://juno33.com)
 * to verify critical routes respond correctly after deploy.
 */

test.describe("Smoke — public routes", () => {
	test("/ returns 200", async ({ page }) => {
		const res = await page.goto("/");
		expect(res?.status()).toBe(200);
	});

	test("/privacy returns 200", async ({ page }) => {
		const res = await page.goto("/privacy");
		expect(res?.status()).toBe(200);
	});

	test("/terms returns 200", async ({ page }) => {
		const res = await page.goto("/terms");
		expect(res?.status()).toBe(200);
	});

	test("sitemap.xml is accessible", async ({ request }) => {
		const res = await request.get("/sitemap.xml");
		expect(res.status()).toBe(200);
		const body = await res.text();
		expect(body).toContain("<urlset");
	});

	test("robots.txt blocks /dashboard", async ({ request }) => {
		const res = await request.get("/robots.txt");
		expect(res.status()).toBe(200);
		const body = await res.text();
		expect(body).toContain("/dashboard");
	});
});

test.describe("Smoke — auth routes", () => {
	test("/login page renders", async ({ page }) => {
		await page.goto("/login");
		// Should show a login form or redirect — not a 500
		await expect(page.locator("body")).not.toContainText("Internal Server Error");
		await expect(page.locator("body")).not.toContainText("Application error");
	});

	test("/signup page renders", async ({ page }) => {
		await page.goto("/signup");
		await expect(page.locator("body")).not.toContainText("Internal Server Error");
	});
});
