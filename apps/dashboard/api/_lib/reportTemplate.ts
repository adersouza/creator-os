/**
 * Report Email Template - Inline-CSS HTML for weekly/monthly reports
 */

export interface AIReportInsights {
	topInsight: string;
	biggestWin: string;
	areaToImprove: string;
	recommendedAction: string;
}

export interface ReportData {
	userName: string;
	periodLabel: string;
	followerGain: number;
	totalFollowers: number;
	totalViews: number;
	avgEngagement: number;
	postsPublished: number;
	topPosts: { content: string; likes: number; replies: number }[];
	aiInsights?: AIReportInsights | null | undefined;
	revenueData?: {
        		totalClicks: number;
        		totalConversions: number;
        		totalRevenue: number;
        		topLink?: string | undefined;
        	} | null | undefined;
}

export function buildWeeklyReportHtml(data: ReportData): string {
	const topPostsHtml = data.topPosts
		.slice(0, 3)
		.map(
			(post, i) => `
      <tr>
        <td style="padding: 12px 16px; border-bottom: 1px solid #f0f0f0;">
          <div style="font-size: 12px; color: #888; margin-bottom: 4px;">#${i + 1}</div>
          <div style="font-size: 14px; color: #333; line-height: 1.4;">
            ${escapeHtml(post.content.substring(0, 120))}${post.content.length > 120 ? "..." : ""}
          </div>
          <div style="margin-top: 8px; font-size: 12px; color: #666;">
            <span style="margin-right: 16px;">&#x2764; ${post.likes} likes</span>
            <span>&#x1F4AC; ${post.replies} replies</span>
          </div>
        </td>
      </tr>
    `,
		)
		.join("");

	const followerDirection = data.followerGain >= 0 ? "+" : "";

	return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; background-color: #f5f5f5; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 40px 20px;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
          <!-- Header -->
          <tr>
            <td style="background: linear-gradient(135deg, #10b981, #06b6d4); padding: 32px 24px; text-align: center;">
              <h1 style="margin: 0; color: #ffffff; font-size: 22px; font-weight: 700;">
                Juno33 Report
              </h1>
              <p style="margin: 8px 0 0; color: rgba(255,255,255,0.85); font-size: 14px;">
                ${escapeHtml(data.periodLabel)}
              </p>
            </td>
          </tr>

          <!-- Greeting -->
          <tr>
            <td style="padding: 24px 24px 8px;">
              <p style="margin: 0; font-size: 16px; color: #333;">
                Hi ${escapeHtml(data.userName)}, here's your performance summary.
              </p>
            </td>
          </tr>

          <!-- Metrics Grid -->
          <tr>
            <td style="padding: 16px 24px;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td width="50%" style="padding: 8px;">
                    <div style="background: #f8fffe; border: 1px solid #d1fae5; border-radius: 8px; padding: 16px; text-align: center;">
                      <div style="font-size: 24px; font-weight: 700; color: #10b981;">
                        ${followerDirection}${formatNum(data.followerGain)}
                      </div>
                      <div style="font-size: 12px; color: #666; margin-top: 4px;">Follower Growth</div>
                      <div style="font-size: 11px; color: #999; margin-top: 2px;">Total: ${formatNum(data.totalFollowers)}</div>
                    </div>
                  </td>
                  <td width="50%" style="padding: 8px;">
                    <div style="background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 8px; padding: 16px; text-align: center;">
                      <div style="font-size: 24px; font-weight: 700; color: #3b82f6;">
                        ${formatNum(data.totalViews)}
                      </div>
                      <div style="font-size: 12px; color: #666; margin-top: 4px;">Total Views</div>
                    </div>
                  </td>
                </tr>
                <tr>
                  <td width="50%" style="padding: 8px;">
                    <div style="background: #fefce8; border: 1px solid #fde68a; border-radius: 8px; padding: 16px; text-align: center;">
                      <div style="font-size: 24px; font-weight: 700; color: #f59e0b;">
                        ${data.avgEngagement.toFixed(1)}%
                      </div>
                      <div style="font-size: 12px; color: #666; margin-top: 4px;">Avg Engagement</div>
                    </div>
                  </td>
                  <td width="50%" style="padding: 8px;">
                    <div style="background: #fdf4ff; border: 1px solid #e9d5ff; border-radius: 8px; padding: 16px; text-align: center;">
                      <div style="font-size: 24px; font-weight: 700; color: #8b5cf6;">
                        ${data.postsPublished}
                      </div>
                      <div style="font-size: 12px; color: #666; margin-top: 4px;">Posts Published</div>
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          ${
						data.revenueData && data.revenueData.totalClicks > 0
							? `
          <!-- Revenue from Smart Links -->
          <tr>
            <td style="padding: 0 24px 16px;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="padding: 0 8px;">
                    <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px; text-align: center;">
                      <div style="font-size: 24px; font-weight: 700; color: #16a34a;">
                        $${data.revenueData.totalRevenue.toFixed(2)}
                      </div>
                      <div style="font-size: 12px; color: #666; margin-top: 4px;">Revenue from Links</div>
                      <div style="font-size: 11px; color: #999; margin-top: 2px;">
                        ${formatNum(data.revenueData.totalClicks)} clicks &bull; ${formatNum(data.revenueData.totalConversions)} conversions${data.revenueData.topLink ? ` &bull; Top: ${escapeHtml(data.revenueData.topLink)}` : ""}
                      </div>
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>`
							: ""
					}

          ${
						data.topPosts.length > 0
							? `
          <!-- Top Posts -->
          <tr>
            <td style="padding: 8px 24px;">
              <h2 style="margin: 0 0 12px; font-size: 16px; font-weight: 600; color: #333;">
                Top Posts
              </h2>
              <table width="100%" cellpadding="0" cellspacing="0" style="border: 1px solid #f0f0f0; border-radius: 8px; overflow: hidden;">
                ${topPostsHtml}
              </table>
            </td>
          </tr>`
							: ""
					}

          ${
						data.aiInsights
							? `
          <!-- AI Insights -->
          <tr>
            <td style="padding: 8px 24px 16px;">
              <h2 style="margin: 0 0 12px; font-size: 16px; font-weight: 600; color: #333;">
                &#x1F9E0; AI Insights
              </h2>
              <table width="100%" cellpadding="0" cellspacing="0" style="border: 1px solid #e0e7ff; border-radius: 8px; overflow: hidden; background: #f5f3ff;">
                <tr>
                  <td style="padding: 14px 16px; border-bottom: 1px solid #e0e7ff;">
                    <div style="font-size: 11px; color: #7c3aed; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">Top Insight</div>
                    <div style="font-size: 13px; color: #333; line-height: 1.4;">${escapeHtml(data.aiInsights.topInsight)}</div>
                  </td>
                </tr>
                <tr>
                  <td style="padding: 14px 16px; border-bottom: 1px solid #e0e7ff;">
                    <div style="font-size: 11px; color: #059669; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">&#x1F3C6; Biggest Win</div>
                    <div style="font-size: 13px; color: #333; line-height: 1.4;">${escapeHtml(data.aiInsights.biggestWin)}</div>
                  </td>
                </tr>
                <tr>
                  <td style="padding: 14px 16px; border-bottom: 1px solid #e0e7ff;">
                    <div style="font-size: 11px; color: #dc2626; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">&#x26A0; Area to Improve</div>
                    <div style="font-size: 13px; color: #333; line-height: 1.4;">${escapeHtml(data.aiInsights.areaToImprove)}</div>
                  </td>
                </tr>
                <tr>
                  <td style="padding: 14px 16px;">
                    <div style="font-size: 11px; color: #2563eb; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">&#x1F4A1; Recommended Action</div>
                    <div style="font-size: 13px; color: #333; line-height: 1.4;">${escapeHtml(data.aiInsights.recommendedAction)}</div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>`
							: ""
					}

          <!-- Footer -->
          <tr>
            <td style="padding: 24px; text-align: center; border-top: 1px solid #f0f0f0;">
              <p style="margin: 0; font-size: 12px; color: #999;">
                Sent by Juno33 &bull; Manage reports in Settings
              </p>
              <p style="margin: 8px 0 0; font-size: 10px; color: #bbb;">
                Powered by Juno33 &mdash; juno33.com
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>`;
}

function escapeHtml(str: string): string {
	return str
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;");
}

function formatNum(n: number): string {
	if (Math.abs(n) >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
	if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)}K`;
	return n.toString();
}
