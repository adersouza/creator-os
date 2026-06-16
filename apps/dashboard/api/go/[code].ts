/**
 * Smart Redirect Engine
 * GET/HEAD /api/go/{code}  (rewritten from /go/{code})
 *
 * Public endpoint — no auth required.
 * Detects source platform + device, serves optimal redirect:
 * - In-app browser → deepview landing page with canonical web fallback
 * - Mobile browser + deep link enabled → user-initiated app open page + web fallback
 * - Desktop / normal web → direct 302 to canonical target
 *
 * Performance target: <100ms. Hot links cached in Redis (5 min TTL).
 */

import * as crypto from "node:crypto";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError } from "../_lib/apiResponse.js";
import { logger } from "../_lib/logger.js";
import { validatePublicRedirectUrl } from "../_lib/outboundUrlSecurity.js";
import {
	appendUtms,
	detectDevice,
	detectPlatform,
	generateFingerprint,
	isCrawler,
	isInAppBrowser,
	parseUtmParams,
} from "../_lib/platformDetect.js";
import {
	getPrivilegedSupabase,
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "../_lib/privilegedDb.js";
import { checkRateLimit } from "../_lib/rateLimiter.js";

const db = () => getPrivilegedSupabase(PRIVILEGED_DB_REASONS.publicLinkRedirect);
const dbAny = () =>
	getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.publicLinkRedirect);

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "GET" && req.method !== "HEAD" && req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}
	const isHead = req.method === "HEAD";

	const appOrigin =
		process.env.APP_URL ||
		(process.env.VERCEL_URL
			? `https://${process.env.VERCEL_URL}`
			: "https://juno33.com");
	res.setHeader("Access-Control-Allow-Origin", appOrigin);

	const code = req.query.code as string;
	if (!code) return res.status(404).send("Not found");

	// Rate limit: 200/hour per IP (fail closed to prevent enumeration)
	const ip =
		(req.headers["x-forwarded-for"] as string)?.split(",")[0]?.trim() ||
		"unknown";
	const rl = await checkRateLimit({
		key: `go:${ip}`,
		limit: 200,
		windowSeconds: 3600,
		failMode: "closed",
	});
	if (!rl.allowed) {
		return res.status(429).send("Too many requests");
	}

	const ua = (req.headers["user-agent"] as string) || "";
	const referrer = (req.headers.referer as string) || "";

	// Skip tracking for crawlers so analytics reflect human visits only.
	const crawler = isCrawler(ua);

	try {
		// Fetch link — use Redis cache for hot links
		let link: {
			id: string;
			code: string;
			target_url: string;
			title: string | null;
			ig_deep_link: string | null;
			threads_deep_link: string | null;
			ig_redirect_url: string | null;
			threads_redirect_url: string | null;
			mobile_redirect_url: string | null;
			is_active: boolean | null;
			enable_deep_links: boolean | null;
			blocks?:
				| Array<{
						id?: string | undefined;
						blockType?: string | undefined;
						metadata?: Record<string, unknown> | undefined;
				  }>
				| null
				| undefined;
			metadata?: Record<string, unknown> | null | undefined;
		} | null;
		try {
			const { cached } = await import("../_lib/redisCache.js");
			link = await cached(`smartlink:${code}`, 300, async () => {
				const { data } = await dbAny()
					.from("smart_links")
					.select(
						"id, code, target_url, title, ig_deep_link, threads_deep_link, ig_redirect_url, threads_redirect_url, mobile_redirect_url, is_active, enable_deep_links, blocks, metadata",
					)
					.eq("code", code)
					.eq("is_active", true)
					.maybeSingle();
				return data;
			});
		} catch {
			// Redis unavailable — fallback to direct DB
			const { data } = await dbAny()
				.from("smart_links")
				.select(
					"id, code, target_url, title, ig_deep_link, threads_deep_link, ig_redirect_url, threads_redirect_url, mobile_redirect_url, is_active, enable_deep_links, blocks, metadata",
				)
				.eq("code", code)
				.eq("is_active", true)
				.maybeSingle();
			link = data;
		}

		if (!link) {
			return res.status(404).send("Link not found");
		}

		const platform = detectPlatform(ua, referrer);
		const device = detectDevice(ua);
		const inApp = isInAppBrowser(ua);
		const incomingUtms = parseUtmParams(req.query);
		const blockedTarget = await validatePublicRedirectUrl(
			link.target_url,
			"smart-link-target",
		);
		if (blockedTarget) {
			logger.warn("[smart-redirect] Blocked unsafe stored target URL", {
				code,
				linkId: link.id,
				reason: blockedTarget,
			});
			return res.redirect(302, appOrigin);
		}

		// #710: Validate and cap UTM param lengths (max 100 chars each)
		const capUtm = (v: string | undefined, fallback: string): string =>
			(v && v.length <= 100 ? v : fallback).slice(0, 100);

		// Build UTM params (Link Page Conversion 2026, Section 10)
		// Convention: utm_source={platform}, utm_medium={context}, utm_campaign={code}
		// utm_content={device}-{inApp} for attribution granularity
		const utms = {
			utm_source: capUtm(incomingUtms.utm_source, platform),
			utm_medium: capUtm(
				incomingUtms.utm_medium,
				inApp ? "in-app" : "smartlink",
			),
			utm_campaign: capUtm(incomingUtms.utm_campaign, code),
			utm_content: capUtm(
				incomingUtms.utm_content,
				`${device}-${inApp ? "inapp" : "browser"}`,
			),
		};

		// Smart links intentionally use one canonical web destination for all
		// visitors. App deep links may vary by platform, but the web fallback
		// must remain constant to avoid destination-based cloaking behavior.
		const finalUrl = appendUtms(link.target_url, utms);
		const nonce = crypto.randomUUID();
		const pixelScripts = renderPixelScripts(link.metadata, nonce);
		const shouldEscapeInApp = Boolean(
			link.blocks?.some((block) => block.metadata?.escapeInApp === true),
		);
		const browserUrl =
			inApp && shouldEscapeInApp
				? appendFlag(finalUrl, "openExternally", "1")
				: finalUrl;
		const smartLinkUrl = `${appOrigin}/go/${encodeURIComponent(code)}`;
		const destinationHost = formatDestinationHost(finalUrl);
		const appearance = getSmartLinkAppearance(
			link.metadata,
			link.title,
			destinationHost,
			appOrigin,
		);
		const destinationBadgeHtml = renderDestinationBadge(destinationHost);
		const handleHtml = renderHandle(appearance.handle);
		const requiresCreatorInterstitial = shouldUseCreatorInterstitial(finalUrl);
		const publicOrigin = getPublicLinkOrigin(req);
		const canonicalSmartLinkUrl = publicOrigin
			? `${publicOrigin}/`
			: smartLinkUrl;

		// Determine if we should attempt deep link
		const shouldDeepLink =
			link.enable_deep_links &&
			!inApp &&
			!crawler &&
			device !== "desktop" &&
			(link.ig_deep_link || link.threads_deep_link);

		if (req.method === "POST") {
			if (!crawler) {
				await trackSmartLinkEvent({
					linkId: link.id,
					eventName: "destination_click",
					platform,
					device,
					ip,
					ua,
					referrer,
					utms,
					deepLinkAttempted: Boolean(shouldDeepLink),
					incrementClickCount: true,
					country: (req.headers["x-vercel-ip-country"] as string) || null,
				});
			}
			return res.status(204).send("");
		}

		// ════════════════════════════════════════════════════════════
		// DESKTOP / CRAWLERS: fast redirect for normal destinations. Creator
		// destinations use the visible interstitial for transparency.
		// ════════════════════════════════════════════════════════════
		if (
			!requiresCreatorInterstitial &&
			(crawler || device === "desktop" || (!inApp && !shouldDeepLink))
		) {
			if (!crawler && !isHead) {
				await trackSmartLinkEvent({
					linkId: link.id,
					eventName: "redirect",
					platform,
					device,
					ip,
					ua,
					referrer,
					utms,
					deepLinkAttempted: false,
					incrementClickCount: true,
					country: (req.headers["x-vercel-ip-country"] as string) || null,
				});
			}
			res.setHeader("Cache-Control", "private, no-cache");
			return res.redirect(302, finalUrl);
		}

		if (!crawler && !isHead) {
			await trackSmartLinkEvent({
				linkId: link.id,
				eventName: "interstitial_view",
				platform,
				device,
				ip,
				ua,
				referrer,
				utms,
				deepLinkAttempted: Boolean(shouldDeepLink),
				incrementClickCount: false,
				country: (req.headers["x-vercel-ip-country"] as string) || null,
			});
		}

		// ════════════════════════════════════════════════════════════
		// IN-APP BROWSER: Deepview landing page with CTA button
		// Deep links are blocked in IG/Threads/FB/TikTok webviews.
		// Show a branded page with "Open in app" button instead.
		// ════════════════════════════════════════════════════════════
		if (inApp || requiresCreatorInterstitial) {
			// Determine Smart App Banner meta tag (iOS only, Safari-based webviews)
			const appBannerMeta = buildSmartAppBanner(finalUrl, platform);
			const interstitialHint = inApp
				? "If Instagram keeps this inside the app, tap <strong>&#8943;</strong> &rarr; <strong>Open in Browser</strong>. No hidden redirects or auto-launches."
				: "This page shows the destination before opening it. No hidden redirects or auto-launches.";

			const deepviewHtml = `<!DOCTYPE html>
	<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
	<title>${escapeHtml(appearance.previewTitle)}</title>
	<meta property="og:type" content="website">
	<meta property="og:title" content="${escapeHtml(appearance.previewTitle)}">
	<meta property="og:description" content="${escapeHtml(appearance.previewDescription)}">
	<meta property="og:image" content="${escapeHtml(appearance.ogImage)}">
	<meta property="og:image:width" content="1200">
	<meta property="og:image:height" content="630">
	<meta name="twitter:card" content="summary_large_image">
	<meta name="twitter:title" content="${escapeHtml(appearance.previewTitle)}">
	<meta name="twitter:description" content="${escapeHtml(appearance.previewDescription)}">
	<meta name="twitter:image" content="${escapeHtml(appearance.ogImage)}">
	<meta property="og:url" content="${escapeHtml(canonicalSmartLinkUrl)}">
	<link rel="canonical" href="${escapeHtml(canonicalSmartLinkUrl)}">
${appBannerMeta}
${pixelScripts}
<style>
*{margin:0;padding:0;box-sizing:border-box}
html{height:100%}
body{min-height:100%;background:linear-gradient(145deg,#0f0f0f 0%,#1a1025 30%,#0d1117 60%,#0f0f0f 100%);color:#fff;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;display:flex;align-items:center;justify-content:center;text-align:center;padding:24px 16px;position:relative;overflow-x:hidden}
body::before{content:'';position:fixed;top:-40%;left:-20%;width:80%;height:80%;background:radial-gradient(circle,rgba(139,92,246,.08) 0%,transparent 70%);pointer-events:none;z-index:0}
body::after{content:'';position:fixed;bottom:-30%;right:-20%;width:70%;height:70%;background:radial-gradient(circle,rgba(236,72,153,.06) 0%,transparent 70%);pointer-events:none;z-index:0}
.escape{display:${shouldEscapeInApp ? "flex" : "none"};position:fixed;left:12px;right:12px;top:12px;padding:12px 16px;border-radius:16px;background:rgba(255,255,255,.06);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,.1);font-size:13px;color:#e4e4e7;z-index:10;align-items:center;justify-content:center;gap:6px}
.c{position:relative;z-index:1;padding:40px 28px 32px;max-width:400px;width:100%;background:rgba(255,255,255,.04);backdrop-filter:blur(40px);-webkit-backdrop-filter:blur(40px);border:1px solid rgba(255,255,255,.08);border-radius:28px;box-shadow:0 8px 32px rgba(0,0,0,.4),0 0 0 1px rgba(255,255,255,.05) inset}
.avatar-wrap{position:relative;width:140px;height:140px;margin:0 auto 20px;border-radius:50%;padding:3px;background:linear-gradient(135deg,#8b5cf6,#ec4899,#f97316);animation:avatar-glow 3s ease-in-out infinite alternate}
.avatar-wrap img{width:100%;height:100%;border-radius:50%;object-fit:cover;border:3px solid #0f0f0f}
@keyframes avatar-glow{0%{box-shadow:0 0 20px rgba(139,92,246,.3),0 0 40px rgba(139,92,246,.1)}100%{box-shadow:0 0 25px rgba(236,72,153,.3),0 0 50px rgba(236,72,153,.1)}}
.hero{display:grid;grid-template-columns:repeat(${Math.min(appearance.imageUrls.length, 3) || 1},1fr);gap:8px;margin:0 0 20px}
.hero img{width:100%;aspect-ratio:1/1;object-fit:cover;border-radius:16px;border:1px solid rgba(255,255,255,.1)}
h2{font-size:22px;font-weight:700;margin-bottom:6px;letter-spacing:-.01em;background:linear-gradient(to right,#fff,#d4d4d8);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.handle{color:#8b5cf6;font-size:13px;font-weight:500;margin-bottom:12px;letter-spacing:.02em}
p.bio{color:#a1a1aa;font-size:14px;line-height:1.6;margin-bottom:24px;max-width:320px;margin-left:auto;margin-right:auto}
.links-section{display:flex;flex-direction:column;gap:10px;margin-bottom:16px}
.btn{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;padding:15px 24px;border-radius:14px;font-size:15px;font-weight:600;text-decoration:none;text-align:center;transition:all .2s ease;cursor:pointer;border:none;position:relative;overflow:hidden}
.btn:active{transform:scale(0.97)}
.btn-primary{background:linear-gradient(135deg,#8b5cf6 0%,#ec4899 100%);color:#fff;box-shadow:0 4px 15px rgba(139,92,246,.3),0 0 0 1px rgba(255,255,255,.1) inset}
.btn-primary:hover{box-shadow:0 6px 25px rgba(139,92,246,.4);transform:translateY(-1px)}
.btn-secondary{background:rgba(255,255,255,.06);color:#e4e4e7;border:1px solid rgba(255,255,255,.1);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}
.btn-secondary:hover{background:rgba(255,255,255,.1);border-color:rgba(255,255,255,.18)}
.btn-icon{font-size:18px;flex-shrink:0}
.badges-container{display:flex;align-items:center;justify-content:center;gap:8px;margin:0 0 16px;flex-wrap:wrap}
.dest-badge{display:inline-flex;align-items:center;gap:6px;padding:6px 14px;margin:0;border-radius:999px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);color:#71717a;font-size:11px;letter-spacing:.02em}
.footer{color:#3f3f46;font-size:11px;margin-top:20px;line-height:1.6}
.footer a{color:#52525b;text-decoration:none}
@media(prefers-reduced-motion:reduce){.avatar-wrap{animation:none}}
</style>
</head>
<body>
<div class="escape">Open in Safari or Chrome for the best experience.</div>
<div class="c">
	${appearance.avatarUrl ? `<div class="avatar-wrap"><img src="${escapeHtml(appearance.avatarUrl)}" alt="${escapeHtml(appearance.title)}"></div>` : ""}
	${renderHeroImages(appearance.imageUrls)}
	<h2>${escapeHtml(appearance.title)}</h2>
	${handleHtml}
	<p class="bio">${escapeHtml(appearance.subtitle)}</p>
	${destinationBadgeHtml}
	<div class="links-section">
	<a class="btn btn-primary" data-track-destination href="${escapeHtml(browserUrl)}">${escapeHtml(appearance.ctaLabel)}</a>
	<button class="btn btn-secondary" type="button" data-copy-link data-copy-url="${escapeHtml(browserUrl)}">Copy Link</button>
	</div>
	<div class="footer">${interstitialHint}</div>
	</div>
<script nonce="${nonce}">
document.querySelectorAll("[data-copy-link]").forEach(function(button){
  button.addEventListener("click",function(){
    var url=button.getAttribute("data-copy-url")||"";
    if(!url)return;
    var setLabel=function(text){button.textContent=text;};
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(url).then(function(){setLabel("Copied");},function(){setLabel(url);});
    }else{setLabel(url);}
  });
});
document.querySelectorAll("[data-track-destination]").forEach(function(link){
  link.addEventListener("click",function(){
    try{
      var body=JSON.stringify({eventName:"destination_click"});
      var blob=new Blob([body],{type:"application/json"});
      if(navigator.sendBeacon){navigator.sendBeacon(window.location.pathname||"/",blob);}
      else{fetch(window.location.pathname||"/",{method:"POST",body:body,headers:{"Content-Type":"application/json"},keepalive:true}).catch(function(){});}
    }catch(_e){}
  });
});
</script>
</body>
</html>`;
			res.setHeader("Content-Type", "text/html; charset=utf-8");
			setSmartRedirectCsp(res, nonce, appearance);
			res.setHeader("Cache-Control", "private, no-cache");
			if (isHead) return res.status(200).end();
			return res.status(200).send(deepviewHtml);
		}

		// ════════════════════════════════════════════════════════════
		// MOBILE BROWSER (not in-app): user-initiated app open.
		// Avoid automatic app launches or timed fallbacks so the public behavior
		// remains transparent to users and platform crawlers.
		// ════════════════════════════════════════════════════════════
		const deepLink =
			platform === "threads" && link.threads_deep_link
				? link.threads_deep_link
				: link.ig_deep_link || "";

		const targetApp = detectTargetApp(deepLink, finalUrl);
		const appBannerMeta = buildSmartAppBanner(deepLink, platform);
		const appLabel = targetApp.appName || "App";

		const deepLinkHtml = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
	<title>${escapeHtml(appearance.previewTitle)}</title>
	<meta property="og:type" content="website">
	<meta property="og:title" content="${escapeHtml(appearance.previewTitle)}">
	<meta property="og:description" content="${escapeHtml(appearance.previewDescription)}">
	<meta property="og:image" content="${escapeHtml(appearance.ogImage)}">
	<meta property="og:image:width" content="1200">
	<meta property="og:image:height" content="630">
	<meta name="twitter:card" content="summary_large_image">
	<meta name="twitter:title" content="${escapeHtml(appearance.previewTitle)}">
	<meta name="twitter:description" content="${escapeHtml(appearance.previewDescription)}">
	<meta name="twitter:image" content="${escapeHtml(appearance.ogImage)}">
	<meta property="og:url" content="${escapeHtml(canonicalSmartLinkUrl)}">
<link rel="canonical" href="${escapeHtml(canonicalSmartLinkUrl)}">
${appBannerMeta}
${pixelScripts}
<style>
*{margin:0;padding:0;box-sizing:border-box}
html{height:100%}
body{min-height:100%;background:linear-gradient(145deg,#0f0f0f 0%,#1a1025 30%,#0d1117 60%,#0f0f0f 100%);color:#fff;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;display:flex;align-items:center;justify-content:center;text-align:center;padding:24px 16px;position:relative;overflow-x:hidden}
body::before{content:'';position:fixed;top:-40%;left:-20%;width:80%;height:80%;background:radial-gradient(circle,rgba(139,92,246,.08) 0%,transparent 70%);pointer-events:none;z-index:0}
body::after{content:'';position:fixed;bottom:-30%;right:-20%;width:70%;height:70%;background:radial-gradient(circle,rgba(236,72,153,.06) 0%,transparent 70%);pointer-events:none;z-index:0}
.c{position:relative;z-index:1;padding:40px 28px 32px;max-width:400px;width:100%;background:rgba(255,255,255,.04);backdrop-filter:blur(40px);-webkit-backdrop-filter:blur(40px);border:1px solid rgba(255,255,255,.08);border-radius:28px;box-shadow:0 8px 32px rgba(0,0,0,.4),0 0 0 1px rgba(255,255,255,.05) inset}
.avatar-wrap{position:relative;width:140px;height:140px;margin:0 auto 20px;border-radius:50%;padding:3px;background:linear-gradient(135deg,#8b5cf6,#ec4899,#f97316);animation:avatar-glow 3s ease-in-out infinite alternate}
.avatar-wrap img{width:100%;height:100%;border-radius:50%;object-fit:cover;border:3px solid #0f0f0f}
@keyframes avatar-glow{0%{box-shadow:0 0 20px rgba(139,92,246,.3),0 0 40px rgba(139,92,246,.1)}100%{box-shadow:0 0 25px rgba(236,72,153,.3),0 0 50px rgba(236,72,153,.1)}}
.hero{display:grid;grid-template-columns:repeat(${Math.min(appearance.imageUrls.length, 3) || 1},1fr);gap:8px;margin:0 0 20px}
.hero img{width:100%;aspect-ratio:1/1;object-fit:cover;border-radius:16px;border:1px solid rgba(255,255,255,.1)}
h2{font-size:22px;font-weight:700;margin-bottom:6px;letter-spacing:-.01em;background:linear-gradient(to right,#fff,#d4d4d8);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.handle{color:#8b5cf6;font-size:13px;font-weight:500;margin-bottom:12px;letter-spacing:.02em}
p.bio{color:#a1a1aa;font-size:14px;line-height:1.6;margin-bottom:24px}
.links-section{display:flex;flex-direction:column;gap:10px;margin-bottom:16px}
.btn{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;padding:15px 24px;border-radius:14px;font-size:15px;font-weight:600;text-decoration:none;text-align:center;transition:all .2s ease;cursor:pointer;border:none;position:relative;overflow:hidden}
.btn:active{transform:scale(0.97)}
.btn-primary{background:linear-gradient(135deg,#8b5cf6 0%,#ec4899 100%);color:#fff;box-shadow:0 4px 15px rgba(139,92,246,.3),0 0 0 1px rgba(255,255,255,.1) inset}
.btn-primary:hover{box-shadow:0 6px 25px rgba(139,92,246,.4);transform:translateY(-1px)}
.btn-secondary{background:rgba(255,255,255,.06);color:#e4e4e7;border:1px solid rgba(255,255,255,.1);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}
.btn-secondary:hover{background:rgba(255,255,255,.1);border-color:rgba(255,255,255,.18)}
.btn-icon{font-size:18px;flex-shrink:0}
.badges-container{display:flex;align-items:center;justify-content:center;gap:8px;margin:0 0 16px;flex-wrap:wrap}
.dest-badge{display:inline-flex;align-items:center;gap:6px;padding:6px 14px;margin:0;border-radius:999px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);color:#71717a;font-size:11px;letter-spacing:.02em}
.footer{color:#3f3f46;font-size:11px;margin-top:20px;line-height:1.6}
@media(prefers-reduced-motion:reduce){.avatar-wrap{animation:none}}
</style>
</head>
<body>
<div class="c">
${appearance.avatarUrl ? `<div class="avatar-wrap"><img src="${escapeHtml(appearance.avatarUrl)}" alt="${escapeHtml(appearance.title)}"></div>` : ""}
${renderHeroImages(appearance.imageUrls)}
<h2>${escapeHtml(appearance.title)}</h2>
${handleHtml}
<p class="bio">${escapeHtml(appearance.subtitle)}</p>
${destinationBadgeHtml}
<div class="links-section">
${deepLink ? `<a class="btn btn-primary" data-track-destination href="${escapeHtml(deepLink)}"><span class="btn-icon">📱</span>Open in ${escapeHtml(appLabel)}</a>` : ""}
<a class="btn ${deepLink ? 'btn-secondary' : 'btn-primary'}" data-track-destination href="${escapeHtml(finalUrl)}">${escapeHtml(appearance.ctaLabel)}</a>
<button class="btn btn-secondary" type="button" data-copy-link data-copy-url="${escapeHtml(finalUrl)}">Copy Link</button>
</div>
<div class="footer">This page waits for your tap before opening. No hidden redirects.</div>
</div>
<script nonce="${nonce}">
var primary=document.querySelector(".btn-primary");
if(primary)primary.addEventListener("click",function(){this.innerHTML='<span class="btn-icon">⏳</span>Opening...';});
document.querySelectorAll("[data-copy-link]").forEach(function(button){
  button.addEventListener("click",function(){
    var url=button.getAttribute("data-copy-url")||"";
    if(!url)return;
    var setLabel=function(text){button.textContent=text;};
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(url).then(function(){setLabel("Copied");},function(){setLabel(url);});
    }else{setLabel(url);}
  });
});
document.querySelectorAll("[data-track-destination]").forEach(function(link){
  link.addEventListener("click",function(){
    try{
      var body=JSON.stringify({eventName:"destination_click"});
      var blob=new Blob([body],{type:"application/json"});
      if(navigator.sendBeacon){navigator.sendBeacon(window.location.pathname||"/",blob);}
      else{fetch(window.location.pathname||"/",{method:"POST",body:body,headers:{"Content-Type":"application/json"},keepalive:true}).catch(function(){});}
    }catch(_e){}
  });
});
</script>
</body>
</html>`;

		res.setHeader("Content-Type", "text/html; charset=utf-8");
		setSmartRedirectCsp(res, nonce, appearance);
		res.setHeader("Cache-Control", "private, no-cache");
		if (isHead) return res.status(200).end();
		return res.status(200).send(deepLinkHtml);
	} catch (err) {
		logger.error("[smart-redirect] Error", { error: String(err), code });
		return res.redirect(302, appOrigin);
	}
}

/** Extract only the origin (scheme + domain) from a referrer URL to avoid storing PII */
function safeReferrerOrigin(ref: string | null | undefined): string | null {
	if (!ref) return null;
	try {
		return new URL(ref).origin;
	} catch {
		return null;
	}
}

function getPublicLinkOrigin(req: VercelRequest): string | null {
	const raw = req.headers["x-public-link-origin"];
	if (typeof raw !== "string") return null;
	try {
		const parsed = new URL(raw);
		if (parsed.protocol !== "https:" && parsed.protocol !== "http:")
			return null;
		return parsed.origin;
	} catch {
		return null;
	}
}

async function trackSmartLinkEvent({
	linkId,
	eventName,
	platform,
	device,
	ip,
	ua,
	referrer,
	utms,
	deepLinkAttempted,
	incrementClickCount,
	country,
}: {
	linkId: string;
	eventName: "interstitial_view" | "destination_click" | "redirect";
	platform: string;
	device: string;
	ip: string;
	ua: string;
	referrer: string;
	utms: Record<string, string>;
	deepLinkAttempted: boolean;
	incrementClickCount: boolean;
	country: string | null;
}): Promise<void> {
	try {
		const fingerprint = generateFingerprint(ip, ua);
		const dedupeCutoff = new Date(Date.now() - 15 * 60_000).toISOString();
		const looseDb = dbAny();
		const { data: recentClick } = await looseDb
			.from("smart_link_clicks")
			.select("id")
			.eq("smart_link_id", linkId)
			.eq("fingerprint", fingerprint)
			.eq("event_name", eventName)
			.gte("clicked_at", dedupeCutoff)
			.maybeSingle();

		if (recentClick?.id) return;

		const { error } = await looseDb.from("smart_link_clicks").insert({
			smart_link_id: linkId,
			source_platform: platform,
			device_type: device,
			country,
			referrer: safeReferrerOrigin(referrer),
			utm_source: utms.utm_source,
			utm_medium: utms.utm_medium,
			utm_campaign: utms.utm_campaign,
			utm_content: utms.utm_content,
			deep_link_attempted: deepLinkAttempted,
			fingerprint,
			event_name: eventName,
			user_agent_hash: crypto.createHash("sha256").update(ua).digest("hex"),
			ip_hash: crypto.createHash("sha256").update(ip).digest("hex"),
		});

		if (error) {
			logger.warn("[smart-redirect] Click insert failed", {
				linkId,
				eventName,
				error: error.message,
			});
			return;
		}

		if (incrementClickCount) {
			const { error: incrementError } = await db().rpc(
				"increment_smart_link_click",
				{ p_link_id: linkId },
			);
			if (incrementError) {
				logger.warn("[smart-redirect] Click count increment failed", {
					linkId,
					error: incrementError.message,
				});
			}
		}
	} catch (error) {
		logger.warn("[smart-redirect] Tracking failed", {
			linkId,
			eventName,
			error: String(error),
		});
	}
}

function escapeHtml(str: string | null | undefined): string {
	if (!str) return "";
	return String(str)
		.replace(/\\/g, "\\\\")
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;")
		.replace(/'/g, "&#039;")
		.replace(/`/g, "&#96;");
}

function appendFlag(url: string, key: string, value: string): string {
	try {
		const parsed = new URL(url);
		parsed.searchParams.set(key, value);
		return parsed.toString();
	} catch {
		const join = url.includes("?") ? "&" : "?";
		return `${url}${join}${encodeURIComponent(key)}=${encodeURIComponent(value)}`;
	}
}

function formatDestinationHost(url: string): string {
	try {
		return new URL(url).hostname.replace(/^www\./, "");
	} catch {
		return "";
	}
}

function shouldUseCreatorInterstitial(url: string): boolean {
	try {
		const host = new URL(url).hostname.replace(/^www\./, "").toLowerCase();
		return [
			"onlyfans.com",
			"fansly.com",
			"fanvue.com",
			"manyvids.com",
			"justfor.fans",
		].some((domain) => host === domain || host.endsWith(`.${domain}`));
	} catch {
		return false;
	}
}

function metadataObject(
	value: Record<string, unknown> | null | undefined,
	key: string,
): Record<string, unknown> {
	const raw = value?.[key];
	return raw && typeof raw === "object" && !Array.isArray(raw)
		? (raw as Record<string, unknown>)
		: {};
}

function metadataText(
	value: Record<string, unknown>,
	key: string,
	maxLength: number,
): string {
	const raw = value[key];
	if (typeof raw !== "string") return "";
	return raw.trim().slice(0, maxLength);
}

function safeHttpsImageUrl(value: unknown): string {
	if (typeof value !== "string") return "";
	try {
		const parsed = new URL(value.trim());
		if (parsed.protocol !== "https:") return "";
		return parsed.toString();
	} catch {
		return "";
	}
}

type SmartLinkAppearance = {
	title: string;
	subtitle: string;
	previewTitle: string;
	previewDescription: string;
	ctaLabel: string;
	handle: string;
	avatarUrl: string;
	imageUrls: string[];
	ogImage: string;
};

function getSmartLinkAppearance(
	metadata: Record<string, unknown> | null | undefined,
	fallbackTitle: string | null,
	destinationHost: string,
	appOrigin: string,
): SmartLinkAppearance {
	const appearance = metadataObject(metadata, "appearance");
	const title =
		metadataText(appearance, "displayTitle", 90) ||
		fallbackTitle?.trim() ||
		"Open this link";
	const subtitle =
		metadataText(appearance, "subtitle", 180) ||
		(destinationHost
			? `Choose how to open ${destinationHost}.`
			: "Choose how to open this link.");
	const ctaLabel = metadataText(appearance, "ctaLabel", 40) || "Open Link";
	const handle = normalizePublicHandle(
		metadataText(appearance, "handle", 40) ||
			metadataText(appearance, "username", 40),
	);
	const avatarUrl = safeHttpsImageUrl(appearance.avatarUrl);
	const imageUrls = Array.isArray(appearance.imageUrls)
		? appearance.imageUrls.map(safeHttpsImageUrl).filter(Boolean).slice(0, 3)
		: [];
	const previewTitle =
		metadataText(appearance, "previewTitle", 90) || buildPreviewTitle(title);
	const previewDescription =
		metadataText(appearance, "previewDescription", 180) ||
		buildPreviewDescription(title, subtitle, destinationHost);
	const ogImage =
		safeHttpsImageUrl(appearance.previewImageUrl) ||
		`${appOrigin}/og-image.png`;
	return {
		title,
		subtitle,
		previewTitle,
		previewDescription,
		ctaLabel,
		handle,
		avatarUrl,
		imageUrls,
		ogImage,
	};
}

function normalizePublicHandle(value: string): string {
	const handle = value.trim().replace(/^@+/, "");
	if (!handle || handle.length > 40) return "";
	if (!/^[a-zA-Z0-9._]+$/.test(handle)) return "";
	return handle;
}

function renderHandle(handle: string): string {
	if (!handle) return "";
	return `<div class="handle">@${escapeHtml(handle)}</div>`;
}

function renderDestinationBadge(destinationHost: string): string {
	if (!destinationHost) return "";
	return `<div class="badges-container"><div class="dest-badge">Destination: ${escapeHtml(destinationHost)}</div></div>`;
}

function renderHeroImages(imageUrls: string[]): string {
	if (imageUrls.length === 0) return "";
	return `<div class="hero">${imageUrls
		.map((url) => `<img src="${escapeHtml(url)}" alt="">`)
		.join("")}</div>`;
}

function buildPreviewTitle(title: string): string {
	const cleanTitle = title.trim();
	if (cleanTitle.length >= 20) return cleanTitle.slice(0, 90);
	return `${cleanTitle} - Creator Profile Link`.slice(0, 90);
}

function buildPreviewDescription(
	title: string,
	subtitle: string,
	destinationHost: string,
): string {
	const cleanSubtitle = subtitle.trim();
	if (cleanSubtitle.length >= 50) return cleanSubtitle.slice(0, 180);
	const destination = destinationHost
		? ` Destination: ${destinationHost}.`
		: "";
	return `Open ${title.trim()} with a transparent destination preview before continuing.${destination}`.slice(
		0,
		180,
	);
}

function renderPixelScripts(
	metadata: Record<string, unknown> | null | undefined,
	nonce: string,
) {
	const pixels =
		metadata?.pixels &&
		typeof metadata.pixels === "object" &&
		!Array.isArray(metadata.pixels)
			? (metadata.pixels as Record<string, unknown>)
			: {};
	const script: string[] = [];
	const meta = typeof pixels.meta === "string" ? pixels.meta.trim() : "";
	const tiktok = typeof pixels.tiktok === "string" ? pixels.tiktok.trim() : "";
	const pinterest =
		typeof pixels.pinterest === "string" ? pixels.pinterest.trim() : "";
	const google = typeof pixels.google === "string" ? pixels.google.trim() : "";

	if (meta) {
		const id = escapeHtml(meta);
		script.push(
			`<script nonce="${nonce}">!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;t.src=v;t.setAttribute('nonce','${nonce}');s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}(window,document,'script','https://connect.facebook.net/en_US/fbevents.js');fbq('init','${id}');fbq('track','PageView');</script>`,
		);
	}
	if (tiktok) {
		const id = escapeHtml(tiktok);
		script.push(
			`<script nonce="${nonce}">!function(w,d,t){w.TiktokAnalyticsObject=t;var ttq=w[t]=w[t]||[];ttq.methods=["page","track"];ttq.setAndDefer=function(t,e){t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}};for(var i=0;i<ttq.methods.length;i++)ttq.setAndDefer(ttq,ttq.methods[i]);ttq.load=function(e){var n=d.createElement("script");n.async=!0;n.src="https://analytics.tiktok.com/i18n/pixel/events.js?sdkid="+e+"&lib="+t;n.setAttribute('nonce','${nonce}');d.getElementsByTagName("head")[0].appendChild(n)};ttq.load('${id}');ttq.page()}(window,document,'ttq');</script>`,
		);
	}
	if (pinterest) {
		const id = escapeHtml(pinterest);
		script.push(
			`<script nonce="${nonce}">!function(e){if(!window.pintrk){window.pintrk=function(){window.pintrk.queue.push(Array.prototype.slice.call(arguments))};var n=window.pintrk;n.queue=[],n.version="3.0";var t=document.createElement("script");t.async=!0,t.src=e;t.setAttribute('nonce','${nonce}');document.getElementsByTagName("script")[0].parentNode.insertBefore(t,document.getElementsByTagName("script")[0])}}("https://s.pinimg.com/ct/core.js");pintrk('load','${id}');pintrk('page');</script>`,
		);
	}
	if (google) {
		const id = escapeHtml(google);
		script.push(
			`<script async src="https://www.googletagmanager.com/gtag/js?id=${id}" nonce="${nonce}"></script><script nonce="${nonce}">window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}gtag('js',new Date());gtag('config','${id}');</script>`,
		);
	}
	return script.join("\n");
}

function collectImageCspOrigins(appearance: SmartLinkAppearance): string[] {
	const origins = new Set<string>();
	for (const value of [
		appearance.avatarUrl,
		appearance.ogImage,
		...appearance.imageUrls,
	]) {
		if (!value) continue;
		try {
			const parsed = new URL(value);
			if (parsed.protocol === "https:") origins.add(parsed.origin);
		} catch {
			// Appearance image URLs are already sanitized; ignore any invalid value.
		}
	}
	return Array.from(origins).sort();
}

function setSmartRedirectCsp(
	res: VercelResponse,
	nonce: string,
	appearance: SmartLinkAppearance,
): void {
	const imageOrigins = collectImageCspOrigins(appearance);
	res.setHeader(
		"Content-Security-Policy",
		[
			"default-src 'self'",
			`script-src 'nonce-${nonce}' https://connect.facebook.net https://analytics.tiktok.com https://s.pinimg.com https://www.googletagmanager.com`,
			"style-src 'unsafe-inline'",
			`img-src 'self' data: https://www.facebook.com https://analytics.tiktok.com https://ct.pinterest.com https://www.google-analytics.com ${imageOrigins.join(" ")}`.trim(),
			"connect-src 'self' https://www.google-analytics.com",
			"frame-ancestors 'none'",
			"base-uri 'self'",
		].join("; "),
	);
}

/** Detect target app from deep link or URL for intent:// and Smart App Banner */
function detectTargetApp(
	deepLink: string,
	targetUrl: string,
): { androidPackage: string; iosAppId: string; appName: string } {
	const dl = deepLink.toLowerCase();
	const url = targetUrl.toLowerCase();

	if (dl.startsWith("instagram://") || url.includes("instagram.com")) {
		return {
			androidPackage: "com.instagram.android",
			iosAppId: "389801252",
			appName: "Instagram",
		};
	}
	if (
		dl.startsWith("barcelona://") ||
		url.includes("threads.com") ||
		url.includes("threads.net")
	) {
		return {
			androidPackage: "com.instagram.barcelona",
			iosAppId: "6446901002",
			appName: "Threads",
		};
	}
	if (
		dl.startsWith("twitter://") ||
		url.includes("x.com") ||
		url.includes("twitter.com")
	) {
		return {
			androidPackage: "com.twitter.android",
			iosAppId: "333903271",
			appName: "X",
		};
	}
	if (dl.startsWith("snssdk1233://") || url.includes("tiktok.com")) {
		return {
			androidPackage: "com.zhiliaoapp.musically",
			iosAppId: "835599320",
			appName: "TikTok",
		};
	}
	if (
		dl.startsWith("vnd.youtube://") ||
		url.includes("youtube.com") ||
		url.includes("youtu.be")
	) {
		return {
			androidPackage: "com.google.android.youtube",
			iosAppId: "544007664",
			appName: "YouTube",
		};
	}
	return { androidPackage: "", iosAppId: "", appName: "" };
}

/** Build iOS Smart App Banner <meta> tag. Shows "OPEN" in Safari if app installed. */
function buildSmartAppBanner(deepLinkOrUrl: string, _platform: string): string {
	const app = detectTargetApp(deepLinkOrUrl, deepLinkOrUrl);
	if (!app.iosAppId) return "";
	// app-argument passes the deep link URL to the app on open
	const appArg = deepLinkOrUrl.startsWith("http") ? deepLinkOrUrl : "";
	const argStr = appArg ? `, app-argument=${escapeHtml(appArg)}` : "";
	return `<meta name="apple-itunes-app" content="app-id=${app.iosAppId}${argStr}">`;
}
