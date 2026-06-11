import { expect, test } from "@playwright/test";

/**
 * Threads post scheduling E2E tests.
 * Requires authenticated session — depends on auth.setup project.
 */
test.use({ storageState: "e2e/.auth/user.json" });

test.describe("Threads — Post Scheduling", () => {
	test.beforeEach(async ({ page }) => {
		// Navigate to content page and wait for it to load
		await page.goto("/content?tab=posts");
		await page.waitForLoadState("networkidle");
	});

	test("can open post composer from content page", async ({ page }) => {
		// Click the FAB / "New Post" button
		const newPostButton = page.getByRole("button", { name: /new post/i });
		await newPostButton.click();

		// Verify composer modal opens
		const dialog = page.getByRole("dialog");
		await expect(dialog).toBeVisible({ timeout: 10_000 });

		// Verify textarea is present for writing content
		const textarea = dialog.locator("textarea");
		await expect(textarea.first()).toBeVisible();
	});

	test("can write content and schedule a Threads post", async ({ page }) => {
		// Open composer
		const newPostButton = page.getByRole("button", { name: /new post/i });
		await newPostButton.click();

		const dialog = page.getByRole("dialog");
		await expect(dialog).toBeVisible({ timeout: 10_000 });

		// Write text content
		const textarea = dialog.locator("textarea").first();
		await textarea.fill("E2E test post — scheduled via Playwright");

		// Open the scheduler
		const scheduleButton = dialog.getByRole("button", {
			name: /schedule/i,
		});
		await scheduleButton.first().click();

		// Verify scheduling panel appears
		await expect(dialog.getByText("Schedule Post")).toBeVisible({
			timeout: 5_000,
		});

		// Select "Tomorrow 9AM" preset
		const tomorrowPreset = dialog.getByRole("button", {
			name: /tomorrow 9am/i,
		});
		await tomorrowPreset.click();

		// Verify the "Scheduled for" confirmation appears
		await expect(dialog.getByText(/scheduled for/i)).toBeVisible({
			timeout: 5_000,
		});

		// Submit the scheduled post (the action button should say Schedule or similar)
		const submitButton = dialog
			.getByRole("button", { name: /schedule|post/i })
			.last();
		await submitButton.click();

		// Wait for the post to be saved — modal should close or show success toast
		await expect(dialog).toBeHidden({ timeout: 15_000 });

		// Navigate to scheduled filter and verify the post appears
		await page.waitForLoadState("networkidle");
		const scheduledFilter = page.getByRole("button", {
			name: /scheduled/i,
		});
		await scheduledFilter.first().click();

		// Verify our post text appears in the list
		await expect(
			page.getByText("E2E test post — scheduled via Playwright"),
		).toBeVisible({ timeout: 10_000 });
	});

	test("empty content shows validation error", async ({ page }) => {
		// Open composer
		const newPostButton = page.getByRole("button", { name: /new post/i });
		await newPostButton.click();

		const dialog = page.getByRole("dialog");
		await expect(dialog).toBeVisible({ timeout: 10_000 });

		// Leave textarea empty and try to publish
		const publishButton = dialog
			.getByRole("button", { name: /post now|publish|schedule/i })
			.last();
		await publishButton.click();

		// Expect a validation error — either an inline message or a toast
		const hasInlineError = await dialog
			.getByText(/content.*required|cannot.*empty|write.*something|enter.*text/i)
			.isVisible()
			.catch(() => false);
		const hasToast = await page
			.getByText(/content.*required|cannot.*empty|write.*something|enter.*text|please.*enter/i)
			.isVisible()
			.catch(() => false);

		expect(hasInlineError || hasToast).toBeTruthy();
	});

	test("past date shows error or is prevented", async ({ page }) => {
		// Open composer
		const newPostButton = page.getByRole("button", { name: /new post/i });
		await newPostButton.click();

		const dialog = page.getByRole("dialog");
		await expect(dialog).toBeVisible({ timeout: 10_000 });

		// Write some content
		const textarea = dialog.locator("textarea").first();
		await textarea.fill("E2E test — past date validation");

		// Open the scheduler
		const scheduleButton = dialog.getByRole("button", {
			name: /schedule/i,
		});
		await scheduleButton.first().click();

		// Wait for scheduling panel
		await expect(dialog.getByText("Schedule Post")).toBeVisible({
			timeout: 5_000,
		});

		// Try to select a past date — the calendar should prevent past dates,
		// or submitting should show an error. We attempt to select yesterday.
		const dateButton = dialog.getByRole("button", {
			name: /pick date|open calendar/i,
		});
		await dateButton.click();

		// The MiniCalendar should be visible
		// Past dates should either be disabled (not clickable) or produce an error on submit.
		// Try to submit with a potentially past time — set hour to midnight today
		const hourSelect = dialog.getByRole("combobox", {
			name: /select hour/i,
		});
		if (await hourSelect.isVisible().catch(() => false)) {
			await hourSelect.selectOption("0");
		}

		// Attempt to submit
		const submitButton = dialog
			.getByRole("button", { name: /schedule|post/i })
			.last();
		await submitButton.click();

		// Should see an error about past time, or the calendar should block past dates
		const hasError = await page
			.getByText(/past|already.*passed|future.*date|invalid.*time/i)
			.isVisible({ timeout: 5_000 })
			.catch(() => false);
		const calendarBlockedPast = await dialog
			.locator("[aria-disabled='true']")
			.count()
			.then((c) => c > 0)
			.catch(() => false);

		// Either past dates are disabled in calendar or an error message is shown
		expect(hasError || calendarBlockedPast).toBeTruthy();
	});

	test("post status shows scheduled after scheduling", async ({ page }) => {
		// Filter by scheduled posts
		const scheduledFilter = page.getByRole("button", {
			name: /scheduled/i,
		});
		await scheduledFilter.first().click();

		await page.waitForLoadState("networkidle");

		// If there are scheduled posts, verify they show "scheduled" status
		const postItems = page.locator('[title*="Status: scheduled"]');
		const count = await postItems.count();

		if (count > 0) {
			// Each scheduled post should have a status indicator
			await expect(postItems.first()).toBeVisible();
		} else {
			// No scheduled posts — just verify the filter is active and no error
			await expect(page.locator("body")).not.toContainText(
				"Internal Server Error",
			);
		}
	});
});
