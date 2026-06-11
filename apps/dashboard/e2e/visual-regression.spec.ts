import { test, expect } from '@playwright/test';

test.describe('Visual Regression - Glass Components', () => {
  test('ViralPostCard - Default State', async ({ page }) => {
    // Visit the Storybook iframe for this component
    await page.goto('/iframe.html?id=competitors-viralpostcard--default&viewMode=story');
    
    // Wait for the component to be visible and animations to settle
    await page.waitForSelector('article');
    await page.waitForTimeout(500); // Allow spring animations to finish
    
    // Take a screenshot and compare it to the baseline
    await expect(page.locator('article')).toHaveScreenshot('viral-post-card-default.png', {
      threshold: 0.1,
      maxDiffPixelRatio: 0.05,
    });
  });

  test('ViralPostCard - Viral State', async ({ page }) => {
    await page.goto('/iframe.html?id=competitors-viralpostcard--viral&viewMode=story');
    
    await page.waitForSelector('article');
    await page.waitForTimeout(1000); // Allow BorderTrail animation to start
    
    await expect(page.locator('article')).toHaveScreenshot('viral-post-card-viral.png', {
      threshold: 0.2, // Higher threshold for animated components
    });
  });
});
