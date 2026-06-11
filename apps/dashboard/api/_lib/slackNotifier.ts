/**
 * Slack webhook delivery for scheduled reports.
 *
 * Posts a Block Kit message to an incoming webhook URL. No file uploads —
 * webhooks can't do that (needs a bot token). For PDF delivery, pair with
 * email or expose a signed download URL in a future pass.
 */

import { logger } from "./logger.js";

export interface SlackReportSummary {
	/** e.g. "Weekly Report - Apr 17 to Apr 24" */
	periodLabel: string;
	totalFollowers: number;
	followerGain: number;
	totalViews: number;
	postsPublished: number;
	/** Formatted as "2.15%" */
	avgEngagement: string;
	topPost?: { content: string; likes: number; replies: number } | undefined;
	/** Optional: mentioned in footer so recipients know where the PDF went */
	emailRecipient?: string | undefined;
}

export async function sendSlackReportMessage(
	webhookUrl: string,
	summary: SlackReportSummary,
): Promise<{ success: boolean; error?: string | undefined }> {
	if (!webhookUrl.startsWith("https://hooks.slack.com/")) {
		return { success: false, error: "Invalid Slack webhook URL" };
	}

	const gainSign = summary.followerGain >= 0 ? "+" : "";
	const gainText = `${gainSign}${summary.followerGain.toLocaleString()}`;

	const blocks: Array<Record<string, unknown>> = [
		{
			type: "header",
			text: { type: "plain_text", text: summary.periodLabel },
		},
		{
			type: "section",
			fields: [
				{
					type: "mrkdwn",
					text: `*Followers*\n${summary.totalFollowers.toLocaleString()} (${gainText})`,
				},
				{
					type: "mrkdwn",
					text: `*Views*\n${summary.totalViews.toLocaleString()}`,
				},
				{
					type: "mrkdwn",
					text: `*Posts*\n${summary.postsPublished}`,
				},
				{
					type: "mrkdwn",
					text: `*Avg Engagement*\n${summary.avgEngagement}%`,
				},
			],
		},
	];

	if (summary.topPost) {
		const truncated =
			summary.topPost.content.length > 200
				? `${summary.topPost.content.slice(0, 200)}…`
				: summary.topPost.content;
		blocks.push({
			type: "section",
			text: {
				type: "mrkdwn",
				text: `*Top post* · ${summary.topPost.likes.toLocaleString()} likes · ${summary.topPost.replies.toLocaleString()} replies\n>${truncated.replace(/\n/g, "\n>")}`,
			},
		});
	}

	const footerText = summary.emailRecipient
		? `Full PDF sent to ${summary.emailRecipient} · Juno33`
		: "Juno33";
	blocks.push({
		type: "context",
		elements: [{ type: "mrkdwn", text: footerText }],
	});

	try {
		const response = await fetch(webhookUrl, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ blocks }),
			signal: AbortSignal.timeout(10000),
		});
		if (!response.ok) {
			const body = await response.text().catch(() => "");
			return {
				success: false,
				error: `Slack ${response.status}: ${body.slice(0, 120)}`,
			};
		}
		return { success: true };
	} catch (err) {
		logger.warn("Slack webhook delivery failed", {
			error: err instanceof Error ? err.message : String(err),
		});
		return {
			success: false,
			error: err instanceof Error ? err.message : String(err),
		};
	}
}
