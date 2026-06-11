import { expect, test } from "@playwright/test";

/**
 * Full post lifecycle E2E tests: Draft -> Edit -> Schedule -> Delete.
 * Requires authenticated session — depends on auth.setup project.
 */
test.use({ storageState: "e2e/.auth/user.json" });

// Use a unique identifier per run to avoid collisions
const RUN_ID = `e2e-${Date.now()}`;

test.describe("Post Lifecycle", () => {
	test.describe.configure({ mode: "serial" });

	let draftContent: string;
	let editedContent: string;

	test.beforeAll(() => {
		draftContent = `Draft test post ${RUN_ID}`;
		editedContent = `Edited test post ${RUN_ID}`;
	});

	test("1. create a draft and verify it appears in drafts list", async ({
		page,
	}) => {
		await page.goto("/content?tab=posts");
		await page.waitForLoadState("networkidle");

		// Open composer
		const newPostButton = page.getByRole("button", { name: /new post/i });
		await newPostButton.click();

		const dialog = page.getByRole("dialog");
		await expect(dialog).toBeVisible({ timeout: 10_000 });

		// Write draft content
		const textarea = dialog.locator("textarea").first();
		await textarea.fill(draftContent);

		// Save as draft — look for a "Save Draft" or "Save" button
		const saveDraftButton = dialog.getByRole("button", {
			name: /save.*draft|save/i,
		});
		await saveDraftButton.first().click();

		// Modal should close after saving
		await expect(dialog).toBeHidden({ timeout: 15_000 });

		// Navigate to drafts filter
		await page.waitForLoadState("networkidle");
		const draftFilter = page.getByRole("button", { name: /draft/i });
		await draftFilter.first().click();

		await page.waitForLoadState("networkidle");

		// Verify our draft appears in the list
		await expect(page.getByText(draftContent)).toBeVisible({
			timeout: 10_000,
		});
	});

	test("2. edit draft content and verify update is reflected", async ({
		page,
	}) => {
		await page.goto("/content?tab=posts");
		await page.waitForLoadState("networkidle");

		// Navigate to drafts
		const draftFilter = page.getByRole("button", { name: /draft/i });
		await draftFilter.first().click();
		await page.waitForLoadState("networkidle");

		// Find and click on our draft post to edit it
		const draftPost = page.getByText(draftContent);
		await expect(draftPost).toBeVisible({ timeout: 10_000 });
		await draftPost.click();

		// The composer modal should open in edit mode
		const dialog = page.getByRole("dialog");
		await expect(dialog).toBeVisible({ timeout: 10_000 });

		// Clear and update the content
		const textarea = dialog.locator("textarea").first();
		await textarea.clear();
		await textarea.fill(editedContent);

		// Save the updated draft
		const saveButton = dialog.getByRole("button", {
			name: /save.*draft|save|update/i,
		});
		await saveButton.first().click();

		// Wait for modal to close
		await expect(dialog).toBeHidden({ timeout: 15_000 });

		// Verify the updated content appears
		await page.waitForLoadState("networkidle");
		const updatedDraftFilter = page.getByRole("button", {
			name: /draft/i,
		});
		await updatedDraftFilter.first().click();
		await page.waitForLoadState("networkidle");

		await expect(page.getByText(editedContent)).toBeVisible({
			timeout: 10_000,
		});

		// Old content should no longer appear
		await expect(page.getByText(draftContent)).toBeHidden({
			timeout: 5_000,
		});
	});

	test("3. schedule draft and verify status changes to scheduled", async ({
		page,
	}) => {
		await page.goto("/content?tab=posts");
		await page.waitForLoadState("networkidle");

		// Navigate to drafts
		const draftFilter = page.getByRole("button", { name: /draft/i });
		await draftFilter.first().click();
		await page.waitForLoadState("networkidle");

		// Find and click our edited draft
		const draftPost = page.getByText(editedContent);
		await expect(draftPost).toBeVisible({ timeout: 10_000 });
		await draftPost.click();

		// Composer opens in edit mode
		const dialog = page.getByRole("dialog");
		await expect(dialog).toBeVisible({ timeout: 10_000 });

		// Open the scheduler
		const scheduleToggle = dialog.getByRole("button", {
			name: /schedule/i,
		});
		await scheduleToggle.first().click();

		// Wait for scheduling panel
		await expect(dialog.getByText("Schedule Post")).toBeVisible({
			timeout: 5_000,
		});

		// Use "Tomorrow 9AM" preset for a safe future time
		const tomorrowPreset = dialog.getByRole("button", {
			name: /tomorrow 9am/i,
		});
		await tomorrowPreset.click();

		// Confirm "Scheduled for" appears
		await expect(dialog.getByText(/scheduled for/i)).toBeVisible({
			timeout: 5_000,
		});

		// Submit to schedule
		const submitButton = dialog
			.getByRole("button", { name: /schedule|update|save/i })
			.last();
		await submitButton.click();

		// Modal should close
		await expect(dialog).toBeHidden({ timeout: 15_000 });

		// Switch to scheduled filter and verify post is there
		await page.waitForLoadState("networkidle");
		const scheduledFilter = page.getByRole("button", {
			name: /scheduled/i,
		});
		await scheduledFilter.first().click();
		await page.waitForLoadState("networkidle");

		await expect(page.getByText(editedContent)).toBeVisible({
			timeout: 10_000,
		});

		// Verify it's no longer in drafts
		const draftFilterAgain = page.getByRole("button", { name: /draft/i });
		await draftFilterAgain.first().click();
		await page.waitForLoadState("networkidle");

		// The edited content should NOT be in drafts anymore
		await expect(page.getByText(editedContent)).toBeHidden({
			timeout: 5_000,
		});
	});

	test("4. delete post and verify it is removed from list", async ({
		page,
	}) => {
		await page.goto("/content?tab=posts");
		await page.waitForLoadState("networkidle");

		// Navigate to scheduled filter where our post should be
		const scheduledFilter = page.getByRole("button", {
			name: /scheduled/i,
		});
		await scheduledFilter.first().click();
		await page.waitForLoadState("networkidle");

		// Find our post
		const postText = page.getByText(editedContent);
		await expect(postText).toBeVisible({ timeout: 10_000 });

		// Click on the post to open it
		await postText.click();

		const dialog = page.getByRole("dialog");
		await expect(dialog).toBeVisible({ timeout: 10_000 });

		// Look for a delete button within the modal
		const deleteButton = dialog.getByRole("button", { name: /delete/i });
		if (await deleteButton.first().isVisible().catch(() => false)) {
			await deleteButton.first().click();

			// Confirm deletion in the confirmation dialog
			const confirmButton = page.getByRole("button", {
				name: /confirm|yes|delete/i,
			});
			if (await confirmButton.first().isVisible().catch(() => false)) {
				await confirmButton.first().click();
			}
		} else {
			// Close the dialog and try to delete from the list view instead
			await page.keyboard.press("Escape");
			await expect(dialog).toBeHidden({ timeout: 5_000 });

			// Some list views have context menus or action buttons on hover
			// Try right-clicking or finding an inline delete action
			const postRow = page.getByText(editedContent).first();
			await postRow.hover();

			// Look for a trash/delete icon button near the post
			const trashButton = page
				.locator("button")
				.filter({ has: page.locator('[class*="trash"], [class*="Trash"]') })
				.first();

			if (await trashButton.isVisible().catch(() => false)) {
				await trashButton.click();

				// Confirm deletion
				const confirmButton = page.getByRole("button", {
					name: /confirm|yes|delete/i,
				});
				if (
					await confirmButton.first().isVisible().catch(() => false)
				) {
					await confirmButton.first().click();
				}
			}
		}

		// Wait for deletion to complete
		await page.waitForLoadState("networkidle");

		// Verify the post is no longer in the scheduled list
		await expect(page.getByText(editedContent)).toBeHidden({
			timeout: 10_000,
		});

		// Also verify it's not in "All" view
		const allFilter = page.getByRole("button", { name: /^all$/i });
		await allFilter.first().click();
		await page.waitForLoadState("networkidle");

		await expect(page.getByText(editedContent)).toBeHidden({
			timeout: 10_000,
		});
	});
});
