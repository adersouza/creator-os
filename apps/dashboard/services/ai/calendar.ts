import type { Platform } from "../../src/types/platform.js";
import type { WeeklyPlan } from "../../types/aiContent.js";
import type { AIContext } from "./contextEngine.js";
import { contextToSystemPrompt } from "./contextEngine.js";
import { generateContent, parseAIJson } from "./core.js";
import type { VoiceProfile } from "./ideas.js";
import { buildVoiceContext, loadVoiceProfile } from "./voiceHelpers.js";

export const generateWeeklyContentPlan = async (
	topic: string,
	platform: string = "threads",
	postsPerDay: number = 1,
	style: "casual" | "professional" | "witty" = "casual",
	voiceProfile?: VoiceProfile,
	aiContext?: AIContext,
): Promise<WeeklyPlan | null> => {
	let voiceContext = "";
	if (aiContext) {
		voiceContext = contextToSystemPrompt(aiContext);
	} else {
		const vp = voiceProfile ?? (await loadVoiceProfile());
		voiceContext = vp ? buildVoiceContext(vp) : "";
	}
	const totalPosts = postsPerDay * 7;
	const charLimit = platform === "threads" ? 500 : 2200;

	const prompt = `Create a 7-day ${platform} content plan about "${topic}".
${voiceContext}
Style: ${style}
Posts per day: ${postsPerDay} (${totalPosts} total)
Max characters per post: ${charLimit}

For each post include:
- day: The day of the week (Monday through Sunday)
- time: Suggested posting time in HH:MM format (24h)
- content: The full post text ready to publish
- contentType: one of "text", "image", "carousel", "video"
- hook: The opening line/hook of the post

Also include an overall theme name and brief strategy description.

Return ONLY a JSON object like:
{
  "theme": "Theme Name",
  "strategy": "Brief strategy description",
  "posts": [{"day": "Monday", "time": "09:00", "content": "Full post text...", "contentType": "text", "hook": "Opening hook..."}]
}`;

	try {
		const response = await generateContent(prompt);
		const plan = parseAIJson<WeeklyPlan>(response);
		if (!plan || !Array.isArray(plan.posts)) return null;
		return plan;
	} catch {
		return null;
	}
};

// ---------------------------------------------------------------------------
// Calendar Auto-Fill
// ---------------------------------------------------------------------------

export const generateCalendarFill = async (
	days: number,
	postsPerDay: number,
	platform: Platform,
	voiceProfile?: VoiceProfile,
	recentPostSummary?: string,
): Promise<
	Array<{ dayOffset: number; content: string; contentType: string }>
> => {
	const totalPosts = days * postsPerDay;
	const charLimit = platform === "threads" ? 500 : 2200;
	const voiceGuide = voiceProfile?.voice_profile
		? `Writing style: ${voiceProfile.voice_profile}.`
		: "";
	const avoidGuide = recentPostSummary
		? `Avoid topics already covered: ${recentPostSummary}`
		: "";

	const prompt = `Generate ${totalPosts} unique ${platform} posts for the next ${days} days (${postsPerDay} per day).
${voiceGuide}
${avoidGuide}
Max ${charLimit} characters per post.
Mix content types: thought leadership, engagement hooks, personal stories, tips.
${platform === "instagram" ? "Include 3-5 relevant hashtags per post." : ""}

Return ONLY valid JSON array:
[{"dayOffset":0,"content":"Full post text here...","contentType":"text"}]

dayOffset 0 = today, 1 = tomorrow, etc. Distribute posts evenly across days.`;

	try {
		const response = await generateContent(prompt);
		const posts =
			parseAIJson<
				Array<{ dayOffset: number; content: string; contentType: string }>
			>(response);
		if (Array.isArray(posts) && posts.length > 0) return posts;
		return [];
	} catch {
		return [];
	}
};

// ---------------------------------------------------------------------------
// Image-to-Caption (Vision API)
// ---------------------------------------------------------------------------
