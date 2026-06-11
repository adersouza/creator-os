import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, zBool, zNum } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
    server.tool(
        "get_trending_config",
        "[TRENDING] Read trending topics configuration for an account group — keywords, scan frequency, daily cap, and blocklist. Empire tier required.",
        {
            groupId: z.string().describe("Account group ID"),
        },
        async ({ groupId }) => {
            return respond(await api(`/trending-config?groupId=${groupId}`));
        }
    );

    server.tool(
        "set_trending_config",
        "[TRENDING] Create or update trending topics configuration for an account group. Controls auto-posting behavior for trending content. Empire tier required.",
        {
            accountGroupId: z.string().describe("Account group ID"),
            keywords: z.array(z.string()).optional().describe("Keywords to monitor (max 20)"),
            scanFrequencyHours: zNum.optional().describe("Hours between scans (2-12)"),
            dailyPostCap: zNum.optional().describe("Max auto-posts per day (1-10)"),
            blocklist: z.array(z.string()).optional().describe("Words/phrases to never post about (max 100)"),
            enabled: zBool.optional().describe("Enable or disable trending auto-posting"),
        },
        async ({ accountGroupId, keywords, scanFrequencyHours, dailyPostCap, blocklist, enabled }) => {
            return respond(await api("/trending-config", "POST", {
                accountGroupId,
                keywords,
                scan_frequency_hours: scanFrequencyHours,
                daily_post_cap: dailyPostCap,
                blocklist,
                enabled,
            }));
        }
    );
};
