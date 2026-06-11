import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import os from 'os';

(async () => {
    // Save to Desktop per request
    const desktopPath = path.join(os.homedir(), 'Desktop', 'SaaS_Screenshots');
    if (!fs.existsSync(desktopPath)) {
        fs.mkdirSync(desktopPath, { recursive: true });
    }

    const browser = await chromium.launch({ headless: false });
    const context = await browser.newContext({
        viewport: { width: 1440, height: 900 }
    });
    const page = await context.newPage();

    console.log("Navigating to login... 🚨 A BROWSER WINDOW WILL POP UP 🚨");
    console.log("👉 PLEASE LOG IN MANUALLY in the Chrome window. The script is waiting...");
    await page.goto('http://localhost:3000');

    // Wait for the user to login and be redirected to dashboard
    try {
        await page.waitForURL('**/dashboard', { timeout: 90000 });
        console.log("✅ Detected Dashboard! Login successful. Starting screenshot capture...");
    } catch (e) {
        console.error("Timed out waiting for login. Please try running the script again.");
        await browser.close();
        return;
    }

    console.log("Taking screenshots...");

    // Setup function to change platform
    const setPlatform = async (platformStr) => {
        await page.evaluate((plat) => {
            localStorage.setItem("juno33-platform-filter", JSON.stringify({ state: { platform: plat }, version: 0 }));
            window.location.reload();
        }, platformStr);
        await page.waitForTimeout(3000);
    };

    // Pages that look completely identical regardless of the platform filter.
    // We only need to screenshot them ONCE to save time and reduce clutter.
    const globalRoutes = [
        { path: 'calendar', name: 'Calendar' },
        { path: 'ai-studio', name: 'AI_Studio' },
        { path: 'links', name: 'Links_Collabs' },
        { path: 'settings', name: 'Settings' }
    ];

    // Pages that radically change their UI depending on the platform filter
    const platformRoutes = [
        { path: 'dashboard', name: 'Dashboard' },
        { path: 'posts', name: 'Posts' },
        { path: 'inbox', name: 'Inbox' }
    ];

    const analyticsTabs = ['growth', 'posts', 'audience', 'strategy', 'compare', 'network', 'instant'];
    const platforms = ['all', 'threads', 'instagram'];

    // 1. Capture Global Routes once (on "all" platform)
    console.log("--- CAPTURING GLOBAL ROUTES ---");
    await setPlatform("all");
    for (const route of globalRoutes) {
        console.log(`Navigating to ${route.path} (Global)`);
        await page.goto(`http://localhost:3000/${route.path}`);
        await page.waitForTimeout(2000);
        await page.screenshot({ path: path.join(desktopPath, `Global_${route.name}.png`), fullPage: true });
    }

    // 2. Capture Platform-Specific Routes
    for (const platform of platforms) {
        console.log(`\n--- CAPTURING ROUTES FOR: ${platform.toUpperCase()} ---`);
        await setPlatform(platform);

        for (const route of platformRoutes) {
            console.log(`Navigating to ${route.path} on ${platform}`);
            await page.goto(`http://localhost:3000/${route.path}`);
            await page.waitForTimeout(2000);
            await page.screenshot({ path: path.join(desktopPath, `${platform}_${route.name}.png`), fullPage: true });
        }

        // Analytics has tabs
        for (const tab of analyticsTabs) {
            if (platform === 'all' && (tab === 'network' || tab === 'instant')) continue;
            if (platform === 'instagram' && (tab === 'network' || tab === 'instant')) continue;
            
            console.log(`Navigating to analytics?tab=${tab} on ${platform}`);
            await page.goto(`http://localhost:3000/analytics?tab=${tab}`);
            await page.waitForTimeout(2000);
            await page.screenshot({ path: path.join(desktopPath, `${platform}_Analytics_${tab}.png`), fullPage: true });
        }
    }

    await browser.close();
    console.log(`All screenshots captured successfully to: ${desktopPath}`);
})();
