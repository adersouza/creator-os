/**
 * Public Link Page Route
 * GET /api/link-page/{slug}
 *
 * No auth required — this is the public-facing page.
 * Serves HTML with:
 * - Proper OG meta tags for link previews
 * - Multi-link layout
 * - Deeplink escape JavaScript for primary link
 * - Click tracking via /api/link-page/track endpoint
 */

import * as crypto from "node:crypto";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError } from "../_lib/apiResponse.js";
import { getPlatformSvg, isKnownPlatform } from "../_lib/linkPlatforms.js";
import { createLinkTrackingToken } from "../_lib/linkTrackingToken.js";
import { logger } from "../_lib/logger.js";
import { isCrawler, isMetaIntegrityBot } from "../_lib/platformDetect.js";
import {
	getPrivilegedSupabase,
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "../_lib/privilegedDb.js";
import { getRequiredAppBaseUrl } from "../_lib/qstashDefaults.js";
import { checkRateLimit } from "../_lib/rateLimiter.js";

const db = () => getPrivilegedSupabase(PRIVILEGED_DB_REASONS.publicLinkPage);
const dbAny = () =>
	getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.publicLinkPage);

type LinkPageItem = {
  id: string;
  title: string;
  url: string;
  icon?: string | null | undefined;
  position: number;
  is_visible?: boolean | undefined;
  is_primary?: boolean | undefined;
  platform?: string | null | undefined;
  deep_link_url?: string | null | undefined;
  redirect_id?: string | null | undefined;
  style?: {
          bg_color?: string | undefined;
          text_color?: string | undefined;
          border_radius?: number | undefined;
          animation?: string | undefined;
          image_url?: string | undefined;
          image_mode?: "button" | "card" | "background" | undefined;
        } | null | undefined;
  deep_link_config?: {
          enable_deep_link?: boolean | undefined;
          ios_deep_link?: string | undefined;
          android_deep_link?: string | undefined;
        } | null | undefined;
  pricing_config?: {
          original_price?: number | undefined;
          sale_price?: number | undefined;
          currency?: string | undefined;
          period?: string | undefined;
          pennies_per_day?: string | undefined;
          discount_badge?: string | undefined;
          show_strikethrough?: boolean | undefined;
        } | null | undefined;
};

type LinkPageRow = {
  id: string;
  slug: string;
  title?: string | null | undefined;
  bio?: string | null | undefined;
  avatar_url?: string | null | undefined;
  background_color?: string | null | undefined;
  brand_color?: string | null | undefined;
  show_online_badge?: boolean | null | undefined;
  promo_text?: string | null | undefined;
  enable_deeplink_escape?: boolean | null | undefined;
  view_count?: number | null | undefined;
  age_gate?: boolean | null | undefined;
  age_gate_message?: string | null | undefined;
  tracking_pixels?: unknown | undefined;
  shield_mode?: string | null | undefined;
  shield_config?: unknown | undefined;
  geo_rules?: {
          rules?: Array<{
                      countries: string[];
                      action: "redirect" | "block";
                      redirect_url?: string | undefined;
                      message?: string | undefined;
                    }> | undefined;
          default?: string | undefined;
        } | null | undefined;
  created_at?: string | null | undefined;
  updated_at?: string | null | undefined;
  link_items?: LinkPageItem[] | null | undefined;
};

/** Validate hex color strings before injecting into CSS */
function isValidHexColor(c: string): boolean {
  return /^#[0-9a-fA-F]{3,8}$/.test(c);
}

function escapeHtml(str: string | null | undefined): string {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function sanitizePublicOrigin(value: unknown): string | null {
  if (typeof value !== "string" || /[\r\n]/.test(value)) return null;
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return null;
    if (parsed.username || parsed.password || parsed.pathname !== "/") return null;
    return parsed.origin;
  } catch {
    return null;
  }
}

function getPublicLinkOrigin(
  req: VercelRequest,
  fallbackOrigin: string,
): string {
  const proxiedOrigin = sanitizePublicOrigin(req.headers["x-public-link-origin"]);
  if (proxiedOrigin) return proxiedOrigin;
  return fallbackOrigin;
}

/** Render an icon for a link: platform SVG > emoji fallback > favicon > nothing */
function renderIcon(link: {
  platform?: string | null | undefined;
  icon?: string | null | undefined;
  url?: string | undefined;
}): string {
  // If link has a platform field, use its SVG
  if (link.platform && isKnownPlatform(link.platform)) {
    return `<span class="platform-icon">${getPlatformSvg(link.platform)}</span>`;
  }
  // If icon is a known platform ID (backward compat for links created with icon=platformId)
  if (link.icon && isKnownPlatform(link.icon)) {
    return `<span class="platform-icon">${getPlatformSvg(link.icon)}</span>`;
  }
  // Emoji icon
  if (link.icon) {
    return `<span class="link-icon">${escapeHtml(link.icon)}</span>`;
  }
  // Favicon fallback
  if (link.url) {
    return `<img src="/api/favicon?url=${encodeURIComponent(link.url)}" style="width:20px;height:20px;border-radius:4px;flex-shrink:0;" loading="lazy" onerror="this.style.display='none'">`;
  }
  return "";
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (req.method !== "GET") {
    return apiError(res, 405, "Method not allowed");
  }

  // Rate limit public page renders by IP (60 req/min, fail-open)
  const ip =
    (req.headers["x-forwarded-for"] as string)?.split(",")[0]?.trim() ||
    "unknown";
  const rl = await checkRateLimit({
    key: `link-page:${ip}`,
    limit: 60,
    windowSeconds: 60,
    failMode: "open",
  });
  if (!rl.allowed) {
    return apiError(res, 429, "Too many requests");
  }

  const slug =
    typeof req.query.slug === "string"
      ? req.query.slug
      : Array.isArray(req.query.slug)
        ? req.query.slug[0]
        : "";
  if (!slug) return res.status(404).send("Not found");

  const supabase = db();
  let appOrigin = "";
  try {
    appOrigin = getRequiredAppBaseUrl();
  } catch {
    const host =
      typeof req.headers.host === "string" && !/[\r\n,]/.test(req.headers.host)
        ? req.headers.host
        : "";
    const proto =
      typeof req.headers["x-forwarded-proto"] === "string" &&
      (req.headers["x-forwarded-proto"] === "http" ||
        req.headers["x-forwarded-proto"] === "https")
        ? req.headers["x-forwarded-proto"]
        : "https";
    appOrigin = host ? `${proto}://${host}` : "";
  }

  // Fetch page with links
  // Only select public-facing columns (never expose user_id)
  const { data: page, error } = (await supabase
    .from("link_pages")
    .select(
      "id, slug, title, bio, avatar_url, background_color, brand_color, show_online_badge, promo_text, enable_deeplink_escape, view_count, age_gate, age_gate_message, tracking_pixels, shield_mode, shield_config, geo_rules, created_at, updated_at, link_items(id, title, url, icon, position, is_visible, is_primary, platform, deep_link_url, redirect_id, style, deep_link_config, pricing_config)",
    )
    .eq("slug", slug)
    .eq("is_published", true)
    .maybeSingle()) as { data: LinkPageRow | null; error: unknown };

  if (error || !page) {
    return res.status(404).send("Page not found");
  }
  const pageData = page;
  const userAgent = (req.headers["user-agent"] as string) || "";
  const crawlerDetected = isCrawler(userAgent);

  // ================================================================
  // Geo rules are retained as stored config only. Public renders must keep one
  // consistent DOM for crawlers and humans to avoid destination cloaking risk.
  // ================================================================
  const geoRules = pageData.geo_rules;
  if (geoRules?.rules?.length) {
    logger.info("[link-page] Geo rules ignored on public render", {
      pageId: pageData.id,
      ruleCount: geoRules.rules.length,
    });
  }

  // ================================================================
  // Shield: crawl monitoring only (NO content filtering)
  //
  // COMPLIANCE NOTE (March 2026): Two independent audits (Gemini, Grok)
  // confirmed that filtering links based on bot detection constitutes
  // cloaking under Meta's policies. Meta uses residential proxies to
  // compare DOM served to their bots vs real users. Any difference
  // triggers domain-level bans.
  //
  // The Shield now ONLY logs when Meta crawlers visit — it never
  // alters page content. All visitors see the identical DOM.
  // ================================================================
  const shieldMode = (pageData.shield_mode || "off") as
    | "off"
    | "soft"
    | "strict";
  const clientIp =
    ((req.headers["x-forwarded-for"] as string) || "").split(",")[0]?.trim() ||
    "";
  const shieldDetection =
    shieldMode !== "off"
      ? isMetaIntegrityBot(
          userAgent,
          req.headers as Record<string, string | string[] | undefined>,
          clientIp,
        )
      : { isBot: false, botType: null };
  const metaCrawlDetected = shieldMode !== "off" && shieldDetection.isBot;

  // Log crawl detection (fire-and-forget) — analytics only, no content change
  if (metaCrawlDetected) {
    const shieldCountry =
      (req.headers["x-vercel-ip-country"] as string) || null;
    Promise.resolve(
      dbAny().from("shield_log").insert({
        page_id: pageData.id,
        bot_type: shieldDetection.botType,
        shield_mode: shieldMode,
        country: shieldCountry,
      }),
    ).catch((err: unknown) =>
      logger.warn("[link-page] Shield log insert failed", {
        error: String(err),
      }),
    );
  }

  // Sort links by position, filter visible
  const links = (pageData.link_items || [])
    .filter((l) => l.is_visible)
    .sort((a, b) => a.position - b.position);

  // ================================================================
  // Extract sameAs social URLs for JSON-LD structured data
  // ================================================================
  const sameAs: string[] = [];
  for (const link of links) {
    if (link.platform && isKnownPlatform(link.platform) && link.url) {
      sameAs.push(link.url);
    }
  }

  // Increment view count atomically (fire and forget).
  // View counts are best-effort analytics — minor underreporting from
  // dropped promises or cold-start timeouts is acceptable and does not
  // affect any business logic or billing calculations.
  if (!crawlerDetected) {
    Promise.resolve(
      supabase.rpc("increment_view_count", { p_page_id: pageData.id }),
    ).catch((err: unknown) =>
      logger.warn("[link-page] Failed to increment_view_count", {
        error: String(err),
      }),
    );
  }

  // ================================================================
  // Thompson Sampling Variant Selection (Link Page Conversion 2026 §7)
  // Selects a variant via Beta distribution sampling, applies config
  // overrides to page data before template rendering.
  // ================================================================
  let selectedVariantId = "";
  try {
    const { data: variants } = await dbAny()
      .from("link_page_variants")
      .select("id, alpha, beta, impressions, conversions, config")
      .eq("page_id", pageData.id)
      .eq("is_active", true);

    if (variants && variants.length > 1) {
      const { selectVariant } = await import("../_lib/thompsonSampling.js");
      selectedVariantId = selectVariant(
        variants.map(
          (v: {
            id: string;
            alpha: number;
            beta: number;
            impressions: number;
            conversions: number;
          }) => ({
            id: v.id,
            alpha: v.alpha,
            beta: v.beta,
            impressions: v.impressions,
            conversions: v.conversions,
          }),
        ),
      );

      const cfg = (
        variants.find((v: { id: string }) => v.id === selectedVariantId) as
          | { config?: Record<string, unknown> | undefined }
          | undefined
      )?.config;

      if (cfg) {
        if (typeof cfg.brand_color === "string") {
          pageData.brand_color = cfg.brand_color;
        }
        if (typeof cfg.bio_text === "string") {
          pageData.bio = cfg.bio_text;
        }
        if (typeof cfg.promo_text === "string") {
          pageData.promo_text = cfg.promo_text;
        }
        if (typeof cfg.cta_text === "string") {
          const primary = links.find((l) => l.is_primary);
          if (primary) primary.title = cfg.cta_text;
        }
        if (
          typeof cfg.max_links === "number" &&
          cfg.max_links > 0 &&
          links.length > cfg.max_links
        ) {
          links.splice(cfg.max_links);
        }
      }

      if (!crawlerDetected) {
        Promise.resolve(
          dbAny().rpc("record_variant_impression", {
            p_variant_id: selectedVariantId,
          }),
        ).catch(() => {});
      }
    }
  } catch {
    // Variant selection is non-critical — fail silently
  }

  // XSS fix: use nonce for inline scripts instead of 'unsafe-inline'
  const nonce = crypto.randomUUID();

  // Validate colors before injecting into CSS to prevent CSS injection.
  // Fall back to safe defaults if stored value is not a valid hex color.
  const rawBrand = pageData.brand_color || "#ff6b9d";
  const rawBg = pageData.background_color || "#0a0a0b";
  const brandColor = isValidHexColor(rawBrand)
    ? escapeHtml(rawBrand)
    : "#ff6b9d";
  const bgColor = isValidHexColor(rawBg) ? escapeHtml(rawBg) : "#0a0a0b";
  const title = escapeHtml(pageData.title || pageData.slug);
  const bio = escapeHtml(pageData.bio || "");
  // Validate avatar URL protocol to prevent javascript:/data: URI injection
  const rawAvatarUrl = pageData.avatar_url || "";
  const avatarUrl =
    rawAvatarUrl && /^https?:\/\//.test(rawAvatarUrl)
      ? escapeHtml(rawAvatarUrl)
      : "";
  const promoText = escapeHtml(pageData.promo_text || "");
  const publicOrigin = getPublicLinkOrigin(req, appOrigin);
  const pageUrl = publicOrigin ? `${publicOrigin}/@${slug}` : `/@${slug}`;

  // ================================================================
  // Tracking Pixel Injection & Dynamic CSP
  // ================================================================
  const pixels = (pageData.tracking_pixels || {}) as Record<string, string>;
  const pixelScripts: string[] = [];
  const pixelNoscripts: string[] = [];
  const extraScriptSrcs: string[] = [];
  const extraImgSrcs: string[] = [];
  const extraConnectSrcs: string[] = [];

  const metaPixelId = pixels.meta_pixel_id || pixels.meta;
  const tiktokPixelId = pixels.tiktok_pixel_id || pixels.tiktok;
  const googleTagId = pixels.ga4_measurement_id || pixels.google;
  const pinterestTagId = pixels.pinterest_tag_id || pixels.pinterest;

  if (metaPixelId) {
    const pid = escapeHtml(metaPixelId);
    extraScriptSrcs.push("https://connect.facebook.net");
    extraImgSrcs.push("https://www.facebook.com");
    pixelScripts.push(
      `<script nonce="${nonce}">!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;t.src=v;t.setAttribute('nonce','${nonce}');s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}(window,document,'script','https://connect.facebook.net/en_US/fbevents.js');fbq('init','${pid}');fbq('track','PageView');</script>`,
    );
    pixelNoscripts.push(
      `<noscript><img height="1" width="1" style="display:none" src="https://www.facebook.com/tr?id=${pid}&amp;ev=PageView&amp;noscript=1"></noscript>`,
    );
  }

  if (tiktokPixelId) {
    const tid = escapeHtml(tiktokPixelId);
    extraScriptSrcs.push("https://analytics.tiktok.com");
    extraImgSrcs.push("https://analytics.tiktok.com");
    pixelScripts.push(
      `<script nonce="${nonce}">!function(w,d,t){w.TiktokAnalyticsObject=t;var ttq=w[t]=w[t]||[];ttq.methods=["page","track","identify","instances","debug","on","off","once","ready","alias","group","enableCookie","disableCookie"];ttq.setAndDefer=function(t,e){t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}};for(var i=0;i<ttq.methods.length;i++)ttq.setAndDefer(ttq,ttq.methods[i]);ttq.instance=function(t){for(var e=ttq._i[t]||[],n=0;n<ttq.methods.length;n++)ttq.setAndDefer(e,ttq.methods[n]);return e};ttq.load=function(e,n){var i="https://analytics.tiktok.com/i18n/pixel/events.js";ttq._i=ttq._i||{};ttq._i[e]=[];ttq._i[e]._u=i;ttq._t=ttq._t||{};ttq._t[e+"-"+n]=+new Date;var o=d.createElement("script");o.type="text/javascript";o.async=!0;o.src=i+"?sdkid="+e+"&lib="+t;o.setAttribute("nonce","${nonce}");d.getElementsByTagName("head")[0].appendChild(o)};ttq.load('${tid}');ttq.page()}(window,document,'ttq');</script>`,
    );
  }

  if (googleTagId) {
    const gid = escapeHtml(googleTagId);
    extraScriptSrcs.push("https://www.googletagmanager.com");
    extraConnectSrcs.push("https://www.google-analytics.com");
    pixelScripts.push(
      `<script async src="https://www.googletagmanager.com/gtag/js?id=${gid}" nonce="${nonce}"></script>`,
    );
    pixelScripts.push(
      `<script nonce="${nonce}">window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}gtag('js',new Date());gtag('config','${gid}');</script>`,
    );
  }

  if (pixels.twitter_pixel_id) {
    const xid = escapeHtml(pixels.twitter_pixel_id);
    extraScriptSrcs.push("https://static.ads-twitter.com");
    extraImgSrcs.push("https://t.co", "https://analytics.twitter.com");
    pixelScripts.push(
      `<script nonce="${nonce}">!function(e,t,n,s,u,a){e.twq||(s=e.twq=function(){s.exe?s.exe.apply(s,arguments):s.queue.push(arguments)},s.version='1.1',s.queue=[],u=t.createElement(n),u.async=!0,u.src='https://static.ads-twitter.com/uwt.js',u.setAttribute('nonce','${nonce}'),a=t.getElementsByTagName(n)[0],a.parentNode.insertBefore(u,a))}(window,document,'script');twq('config','${xid}');twq('track','PageView');</script>`,
    );
  }

  if (pinterestTagId) {
    const pinId = escapeHtml(pinterestTagId);
    extraScriptSrcs.push("https://s.pinimg.com");
    extraImgSrcs.push("https://ct.pinterest.com");
    pixelScripts.push(
      `<script nonce="${nonce}">!function(e){if(!window.pintrk){window.pintrk=function(){window.pintrk.queue.push(Array.prototype.slice.call(arguments))};var n=window.pintrk;n.queue=[],n.version="3.0";var t=document.createElement("script");t.async=!0,t.src=e;t.setAttribute('nonce','${nonce}');document.getElementsByTagName("script")[0].parentNode.insertBefore(t,document.getElementsByTagName("script")[0])}}("https://s.pinimg.com/ct/core.js");pintrk('load','${pinId}');pintrk('page');</script>`,
    );
  }

  if (pixels.snapchat_pixel_id) {
    const sid = escapeHtml(pixels.snapchat_pixel_id);
    extraScriptSrcs.push("https://sc-static.net");
    extraImgSrcs.push("https://tr.snapchat.com");
    pixelScripts.push(
      `<script nonce="${nonce}">(function(e,t,n){if(e.snaptr)return;var a=e.snaptr=function(){a.handleRequest?a.handleRequest.apply(a,arguments):a.queue.push(arguments)};a.queue=[];var s=t.createElement('script');s.async=!0;s.src=n;s.setAttribute('nonce','${nonce}');var r=t.getElementsByTagName('script')[0];r.parentNode.insertBefore(s,r)})(window,document,'https://sc-static.net/scevent.min.js');snaptr('init','${sid}',{});snaptr('track','PAGE_VIEW');</script>`,
    );
  }

  if (pixels.gtm_container_id) {
    const gtmId = escapeHtml(pixels.gtm_container_id);
    extraScriptSrcs.push("https://www.googletagmanager.com");
    pixelScripts.push(
      `<script nonce="${nonce}">(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],j=d.createElement(s),dl=l ='dataLayer'?'&l='+l:'';j.async=true;j.src='https://www.googletagmanager.com/gtm.js?id='+i+dl;j.setAttribute('nonce','${nonce}');f.parentNode.insertBefore(j,f)})(window,document,'script','dataLayer','${gtmId}');</script>`,
    );
    pixelNoscripts.push(
      `<noscript><iframe src="https://www.googletagmanager.com/ns.html?id=${gtmId}" height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>`,
    );
  }

  // Build dynamic CSP script-src
  const baseSrcDirectives = [`'nonce-${nonce}'`];
  const uniqueScriptSrcs = [...new Set(extraScriptSrcs)];
  const scriptSrc = `script-src ${baseSrcDirectives.concat(uniqueScriptSrcs).join(" ")}`;

  const baseImgSrcs = [
    "'self'",
    "https://*.supabase.co",
    "https://*.cdninstagram.com",
    "https://*.fbcdn.net",
  ];
  const uniqueImgSrcs = [...new Set(extraImgSrcs)];
  const imgSrc = `img-src ${baseImgSrcs.concat(uniqueImgSrcs).join(" ")}`;

  const baseConnectSrcs = ["'self'"];
  const uniqueConnectSrcs = [...new Set(extraConnectSrcs)];
  const connectSrc = `connect-src ${baseConnectSrcs.concat(uniqueConnectSrcs).join(" ")}`;

  // ================================================================
  // Link Rendering Helper
  // ================================================================
  function renderLink(link: (typeof links)[number]): string {
    const style = link.style || null;

    // Render the real destination in the href. The click beacon handles
    // analytics; hiding destinations behind a redirect id makes the page look
    // like a shortener/cloak to platform integrity scanners.
    const href = escapeHtml(link.url);

    // Build inline style overrides from per-link style
    const inlineStyles: string[] = [];
    if (style?.bg_color && isValidHexColor(style.bg_color)) {
      inlineStyles.push(`background-color:${escapeHtml(style.bg_color)}`);
    }
    if (style?.text_color && isValidHexColor(style.text_color)) {
      inlineStyles.push(`color:${escapeHtml(style.text_color)}`);
    }
    if (style?.border_radius != null) {
      inlineStyles.push(`border-radius:${Number(style.border_radius)}px`);
    }

    // Animation class
    const animClass = style?.animation
      ? ` anim-${escapeHtml(style.animation)}`
      : "";

    // Deep link config data attribute
    const deepLinkConfigAttr = link.deep_link_config
      ? ` data-deep-config='${escapeHtml(JSON.stringify(link.deep_link_config))}'`
      : "";
    const trackToken = createLinkTrackingToken({
      pageId: pageData.id,
      linkId: link.id,
      variantId: selectedVariantId || null,
    });

    // Common attributes
    const commonAttrs = `href="${href}" class="link-btn ${link.is_primary ? "primary" : ""}${animClass}" data-link-id="${escapeHtml(link.id)}" data-page-id="${escapeHtml(pageData.id)}" data-track-token="${escapeHtml(trackToken)}"${link.deep_link_url ? ` data-deep-link="${escapeHtml(link.deep_link_url)}"` : ""}${link.is_primary && pageData.enable_deeplink_escape ? ' data-escape="true"' : ""}${deepLinkConfigAttr}`;

    // Validate image URL (https only)
    const imageUrl =
      style?.image_url && /^https:\/\//.test(style.image_url)
        ? escapeHtml(style.image_url)
        : null;
    const imageMode = style?.image_mode || "button";

    const icon = renderIcon(link);
    const titleText = escapeHtml(link.title);

    // Strikethrough pricing (Link Page Conversion 2026 §9)
    const pc = link.pricing_config;
    let pricingHtml = "";
    if (pc?.show_strikethrough && pc.sale_price != null) {
      const cur = escapeHtml(pc.currency || "$");
      const per = pc.period ? `/${escapeHtml(pc.period)}` : "";
      if (pc.original_price != null)
        pricingHtml += `<span class="original-price">${cur}${Number(pc.original_price).toFixed(2)}${per}</span>`;
      pricingHtml += `<span class="sale-price">${cur}${Number(pc.sale_price).toFixed(2)}${per}</span>`;
      if (pc.discount_badge)
        pricingHtml += `<span class="discount-badge">${escapeHtml(pc.discount_badge)}</span>`;
      if (pc.pennies_per_day)
        pricingHtml += `<span class="daily-price">just ${cur}${escapeHtml(pc.pennies_per_day)}/day</span>`;
      pricingHtml = `<div class="pricing">${pricingHtml}</div>`;
    }
    const titleBlock = pricingHtml
      ? `<div style="display:flex;flex-direction:column;gap:2px;flex:1;"><span>${titleText}</span>${pricingHtml}</div>`
      : `<span>${titleText}</span>`;

    // Image-as-button modes
    if (imageUrl) {
      if (imageMode === "card") {
        return `<a ${commonAttrs} style="flex-direction:column;padding:0;overflow:hidden;${inlineStyles.join(";")}${inlineStyles.length ? ";" : ""}">
          <img src="${imageUrl}" style="width:100%;height:140px;object-fit:cover;" loading="lazy">
          <div class="card-body">
            ${icon} ${titleBlock} <span class="arrow">&rarr;</span>
          </div>
        </a>`;
      }
      if (imageMode === "background") {
        return `<a ${commonAttrs} style="background-image:url('${imageUrl}');background-size:cover;background-position:center;min-height:80px;${inlineStyles.join(";")}${inlineStyles.length ? ";" : ""}">
          <span style="text-shadow:0 1px 4px rgba(0,0,0,0.7);">${titleText}</span>
          <span class="arrow">&rarr;</span>
        </a>`;
      }
      // Default: "button" mode — image before title
      const styleStr = inlineStyles.length
        ? ` style="${inlineStyles.join(";")}"`
        : "";
      return `<a ${commonAttrs}${styleStr}>
          <img src="${imageUrl}" style="width:40px;height:40px;border-radius:8px;object-fit:cover;flex-shrink:0;" loading="lazy">
          ${titleBlock}
          <span class="arrow">&rarr;</span>
        </a>`;
    }

    // Standard link (no image)
    const styleStr = inlineStyles.length
      ? ` style="${inlineStyles.join(";")}"`
      : "";
    return `<a ${commonAttrs}${styleStr}>
          ${icon}
          ${titleBlock}
          <span class="arrow">&rarr;</span>
        </a>`;
  }

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">

  <!-- Open Graph / link previews -->
  <meta property="og:type" content="website">
  <meta property="og:title" content="${title}">
  <meta property="og:description" content="${bio || "Check out my links"}">
  ${avatarUrl ? `<meta property="og:image" content="${avatarUrl}">` : ""}
  <meta property="og:url" content="${escapeHtml(pageUrl)}">
  <meta name="twitter:card" content="summary">
  <meta name="twitter:title" content="${title}">
  <meta name="twitter:description" content="${bio || "Check out my links"}">
  ${avatarUrl ? `<meta name="twitter:image" content="${avatarUrl}">` : ""}
  <meta property="og:site_name" content="${escapeHtml(pageData.title || "Juno33 Links")}">
  <link rel="canonical" href="${escapeHtml(pageUrl)}">

  <!-- Keywords for discoverability -->
  <meta name="keywords" content="${escapeHtml(pageData.title || slug)}, @${escapeHtml(slug)}, ${escapeHtml(pageData.title || slug)} Juno33, ${escapeHtml(pageData.title || slug)} links, @${escapeHtml(slug)} Juno33">

  <!-- ProfilePage JSON-LD structured data -->
  <script type="application/ld+json" nonce="${nonce}">${JSON.stringify({
    "@context": "https://schema.org/",
    "@type": "ProfilePage",
    dateCreated: pageData.created_at || undefined,
    dateModified: pageData.updated_at || undefined,
    mainEntity: {
      "@type": "Person",
      name: pageData.title || slug,
      alternateName: `@${slug}`,
      identifier: slug,
      ...(pageData.bio ? { description: pageData.bio } : {}),
      ...(pageData.avatar_url ? { image: pageData.avatar_url } : {}),
      url: pageUrl,
      ...(sameAs.length > 0 ? { sameAs } : {}),
    },
    significantLink: pageUrl,
    isPartOf: { "@type": "WebSite", url: `${publicOrigin || appOrigin}/` },
  }).replace(/<\//g, "<\\/")}</script>

  <title>${title}</title>
  <meta name="robots" content="index, follow">

  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">

  ${pixelScripts.join("\n  ")}
  ${pixelNoscripts.join("\n  ")}

  <style>
    :root {
      --brand: ${brandColor};
      --brand-glow: ${brandColor}40;
      --bg: ${bgColor};
    }

    * { margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }

    body {
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--bg);
      color: #fff;
      min-height: 100vh;
      min-height: 100dvh;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 24px;
      padding-top: 48px;
    }

    body::before {
      content: '';
      position: fixed;
      inset: 0;
      background:
        radial-gradient(ellipse 80% 50% at 50% -20%, var(--brand-glow), transparent),
        radial-gradient(ellipse 60% 40% at 80% 100%, #6366f120, transparent);
      pointer-events: none;
    }

    .container {
      position: relative;
      width: 100%;
      max-width: 420px;
      text-align: center;
    }

    .avatar {
      width: 96px;
      height: 96px;
      border-radius: 50%;
      margin: 0 auto 20px;
      background: linear-gradient(135deg, var(--brand), #6366f1);
      padding: 3px;
      animation: pulse 3s ease-in-out infinite;
    }

    .avatar img {
      width: 100%;
      height: 100%;
      border-radius: 50%;
      object-fit: cover;
      background: var(--bg);
    }

    /* CSS-only fallback when avatar image fails to load */
    .avatar img[data-failed] { display: none; }
    .avatar-fallback { display: none; }
    .avatar img[data-failed] + .avatar-fallback { display: flex; }

    .avatar-placeholder {
      width: 100%;
      height: 100%;
      border-radius: 50%;
      background: var(--bg);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 32px;
      font-weight: 700;
      color: var(--brand);
    }

    @keyframes pulse {
      0%, 100% { transform: scale(1); box-shadow: 0 0 0 0 var(--brand-glow); }
      50% { transform: scale(1.01); box-shadow: 0 0 20px 8px var(--brand-glow); }
    }

    h1 { font-size: 22px; font-weight: 700; margin-bottom: 6px; letter-spacing: -0.02em; }

    .bio { color: #a1a1aa; font-size: 14px; margin-bottom: 20px; line-height: 1.4; }

    .online-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: rgba(34, 197, 94, 0.1);
      border: 1px solid rgba(34, 197, 94, 0.2);
      padding: 5px 12px;
      border-radius: 20px;
      font-size: 12px;
      color: #22c55e;
      margin-bottom: 20px;
    }

    .online-dot {
      width: 7px;
      height: 7px;
      background: #22c55e;
      border-radius: 50%;
      animation: blink 1.5s ease-in-out infinite;
    }

    @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

    .promo {
      background: #141416;
      border: 1px solid #ffffff10;
      border-radius: 12px;
      padding: 10px 14px;
      margin-bottom: 20px;
      font-size: 13px;
    }

    .promo-label {
      color: var(--brand);
      font-weight: 600;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 3px;
    }

    .links-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
      width: 100%;
    }

    .link-btn {
      display: flex;
      align-items: center;
      gap: 12px;
      width: 100%;
      padding: 15px 18px;
      background: #141416;
      border: 1px solid #ffffff10;
      border-radius: 14px;
      color: #fff;
      text-decoration: none;
      font-family: inherit;
      font-size: 15px;
      font-weight: 500;
      cursor: pointer;
      transition: transform 0.15s, background 0.15s;
    }

    .link-btn:hover { background: #1c1c1f; transform: translateY(-1px); }
    .link-btn:active { transform: scale(0.98); }

    .link-btn.primary {
      background: linear-gradient(135deg, var(--brand), #d946ef);
      border: none;
      padding: 17px 18px;
      font-size: 16px;
      font-weight: 600;
      box-shadow: 0 4px 20px var(--brand-glow);
    }

    .link-icon { font-size: 18px; flex-shrink: 0; }
    .platform-icon { flex-shrink: 0; display: flex; align-items: center; }
    .platform-icon svg { width: 20px; height: 20px; fill: currentColor; }

    .link-btn .arrow { margin-left: auto; opacity: 0.5; font-size: 14px; }

    .loading-overlay {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.85);
      z-index: 100;
      align-items: center;
      justify-content: center;
      flex-direction: column;
      gap: 16px;
    }

    .loading-overlay.active { display: flex; }

    .inapp-banner {
      display: none;
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      z-index: 90;
      background: #141416;
      border-top: 1px solid #ffffff10;
      padding: 14px 20px;
      text-align: center;
      font-family: inherit;
    }

    .inapp-banner.active { display: block; }

    .inapp-banner p {
      color: #a1a1aa;
      font-size: 13px;
      margin-bottom: 10px;
    }

    .inapp-banner button {
      background: var(--brand);
      color: #fff;
      border: none;
      border-radius: 10px;
      padding: 10px 24px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      font-family: inherit;
    }

    .spinner {
      width: 28px;
      height: 28px;
      border: 2px solid #333;
      border-top-color: var(--brand);
      border-radius: 50%;
      animation: spin 0.7s linear infinite;
    }

    @keyframes spin { to { transform: rotate(360deg); } }

    .loading-text { color: #a1a1aa; font-size: 14px; }

    .footer {
      margin-top: 40px;
      text-align: center;
      color: #52525b;
      font-size: 11px;
    }

    .footer a { color: #71717a; text-decoration: none; }
    .footer a:hover { color: #a1a1aa; }

    /* Per-link animation classes */
    @keyframes pulse-link { 0%,100%{transform:scale(1)} 50%{transform:scale(1.03)} }
    @keyframes shake-link { 0%,100%{transform:translateX(0)} 25%{transform:translateX(-3px)} 75%{transform:translateX(3px)} }
    @keyframes glow-link { 0%,100%{box-shadow:0 0 5px rgba(255,255,255,0.1)} 50%{box-shadow:0 0 20px rgba(255,255,255,0.3)} }
    @keyframes bounce-link { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-4px)} }
    .anim-pulse { animation: pulse-link 2s ease infinite; }
    .anim-shake { animation: shake-link 3s ease infinite; }
    .anim-glow { animation: glow-link 2s ease infinite; }
    .anim-bounce { animation: bounce-link 2s ease infinite; }

    /* Image-as-button card mode */
    .link-card { flex-direction: column; padding: 0; overflow: hidden; }
    .link-card img { width: 100%; height: 140px; object-fit: cover; }
    .link-card .card-body { display: flex; align-items: center; gap: 12px; padding: 15px 18px; width: 100%; }

    /* Strikethrough pricing (Link Page Conversion 2026 §9) */
    .pricing { display:flex;align-items:center;gap:8px;margin-top:2px;font-size:13px;flex-wrap:wrap; }
    .original-price { text-decoration:line-through;color:#71717a;font-size:12px; }
    .sale-price { color:#ef4444;font-weight:700; }
    .discount-badge { background:rgba(239,68,68,0.15);color:#ef4444;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600; }
    .daily-price { color:#71717a;font-size:11px; }
  </style>
</head>
<body>
  <div class="loading-overlay" id="loadingOverlay">
    <div class="spinner"></div>
    <p class="loading-text">Opening in your browser...</p>
  </div>

  <div class="inapp-banner" id="inappBanner">
    <p>For the best experience, open in your browser</p>
    <button id="inappEscapeBtn">Open in Browser</button>
  </div>

  <div class="container">
    <div class="avatar">
      ${
        avatarUrl
          ? `<img src="${avatarUrl}" alt="${title}"><div class="avatar-placeholder avatar-fallback">${escapeHtml((pageData.title || "U").charAt(0).toUpperCase())}</div>`
          : `<div class="avatar-placeholder">${escapeHtml((pageData.title || pageData.slug || "U").charAt(0).toUpperCase())}</div>`
      }
    </div>

    <h1>${title}</h1>
    ${bio ? `<p class="bio">${bio}</p>` : ""}

    ${pageData.show_online_badge ? '<div class="online-badge"><span class="online-dot"></span>Online now</div>' : ""}

    ${
      // Link Page Conversion 2026, Section 4: conditional social proof
      // Only show view count when > 1,000 — low numbers hurt conversion
      (pageData.view_count ?? 0) > 1000
        ? `<div style="color:#71717a;font-size:12px;margin-bottom:12px;">${Number(pageData.view_count).toLocaleString()} views</div>`
        : ""
    }

    ${promoText ? `<div class="promo"><div class="promo-label">Limited Offer</div><div>${promoText}</div></div>` : ""}

    <div class="links-list">
      ${links.map((link) => renderLink(link)).join("")}
    </div>

    <div class="footer">
      <a href="${escapeHtml(appOrigin)}">Powered by Juno33</a>
    </div>
  </div>

  <script nonce="${nonce}">
    // ================================================================
    // Avatar Fallback
    // ================================================================
    document.querySelectorAll('.avatar img').forEach(function(img) {
      img.addEventListener('error', function() {
        this.setAttribute('data-failed', '');
      });
    });

    // ================================================================
    // Click Tracking
    // Uses navigator.sendBeacon() — the industry standard for best-effort
    // analytics pings. Beacon requests survive page navigations and are
    // fire-and-forget by design. No retry is needed; minor data loss on
    // network failure is acceptable for click analytics.
    // ================================================================
    function trackClick(linkId, token) {
      if (!token) return;
      navigator.sendBeacon('/api/link-page/track', JSON.stringify({
        linkId: linkId,
        pageId: '${escapeHtml(pageData.id)}',
        variantId: '${escapeHtml(selectedVariantId)}' || undefined,
        referrer: document.referrer || null,
        token: token,
      }));
    }

    // ================================================================
    // Click Tracking — event delegation for all links
    // ================================================================
    document.querySelectorAll('.link-btn').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var linkId = this.getAttribute('data-link-id');
        var token = this.getAttribute('data-track-token');
        if (linkId) trackClick(linkId, token);
      });
    });

    // ================================================================
    // In-App Browser Detection & Deep Linking
    //
    // Three tiers of link handling:
    // 1. data-deep-link: Try native app deep link (all links with platform detection)
    // 2. data-escape: In-app browser escape (primary link, Pro+ only)
    // 3. Default: Normal web navigation
    //
    // NOTE: UA-based detection is best-effort for UX purposes.
    // It is NOT a security boundary — this is the industry-standard
    // approach used by Linktree, Beacons, and similar link-in-bio tools.
    // ================================================================
    var ua = navigator.userAgent.toLowerCase();
    var isIOS = /iphone|ipad|ipod/.test(ua);
    var isAndroid = /android/.test(ua);
    var isMobile = isIOS || isAndroid;
    var isInApp = /instagram|fban|fbav|fb_iab|tiktok|musical_ly|bytedance|snapchat|twitter|telegram|messenger/.test(ua);

    // Universal deep link handler for ALL links with data-deep-link or data-deep-config
    if (isMobile && !isInApp) {
      document.querySelectorAll('[data-deep-link],[data-deep-config]').forEach(function(btn) {
        btn.addEventListener('click', function(e) {
          var deepLink = null;
          var dest = this.href;

          // Check per-link deep_link_config first (takes priority)
          var deepConfig = null;
          try { deepConfig = JSON.parse(this.getAttribute('data-deep-config') || 'null'); } catch(_e) {}
          if (deepConfig && deepConfig.enable_deep_link !== false) {
            var configDeepUrl = isIOS ? deepConfig.ios_deep_link : deepConfig.android_deep_link;
            if (configDeepUrl) deepLink = configDeepUrl;
          }

          // Fall back to data-deep-link attribute
          if (!deepLink) {
            deepLink = this.getAttribute('data-deep-link');
          }

          if (!deepLink) return; // Let normal navigation proceed

          e.preventDefault();

          // Try native deep link, fallback to web URL after 1.5s
          var didNavigate = false;
          window.location.href = deepLink;
          setTimeout(function() {
            if (!didNavigate) {
              window.location.href = dest;
            }
          }, 1500);
          // If page becomes hidden, the deep link worked
          document.addEventListener('visibilitychange', function() {
            if (document.hidden) didNavigate = true;
          }, { once: true });
        });
      });
    }

    // In-app browser escape — user-initiated only (Meta compliance)
    //
    // As of March 2026, all automatic browser-escape schemes are dead:
    // x-safari-, googlechrome://, and intent:// are all blocked by
    // Instagram's in-app browser. The only working approach is prompting
    // the user to manually open in their native browser.
    //
    // Flow: copy URL to clipboard → show instruction → window.open fallback
    if (isInApp) {
      var escapeBtn = document.querySelectorAll('[data-escape="true"]')[0];
      if (escapeBtn) {
        var banner = document.getElementById('inappBanner');
        banner.classList.add('active');

        document.getElementById('inappEscapeBtn').addEventListener('click', function() {
          var dest = escapeBtn.href;

          banner.classList.remove('active');

          // Track the click
          trackClick(escapeBtn.getAttribute('data-link-id'), escapeBtn.getAttribute('data-track-token'));

          // Copy URL to clipboard so user can paste in their browser
          var overlay = document.getElementById('loadingOverlay');
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(dest).then(function() {
              overlay.querySelector('.loading-text').textContent = 'Link copied! Tap \u22EF then \u201COpen in ' + (isIOS ? 'Safari' : 'Browser') + '\u201D';
              overlay.classList.add('active');
            }).catch(function() {
              overlay.querySelector('.loading-text').textContent = 'Tap \u22EF then \u201COpen in ' + (isIOS ? 'Safari' : 'Browser') + '\u201D';
              overlay.classList.add('active');
            });
          } else {
            overlay.querySelector('.loading-text').textContent = 'Tap \u22EF then \u201COpen in ' + (isIOS ? 'Safari' : 'Browser') + '\u201D';
            overlay.classList.add('active');
          }

          // Fallback: try window.open which may work on some Android WebViews
          try { window.open(dest, '_blank'); } catch(_e) {}
        });
      }
    }
  </script>

  ${
    page.age_gate
      ? `
  <div id="age-gate" style="position:fixed;inset:0;z-index:9999;background:#000;display:flex;align-items:center;justify-content:center;flex-direction:column;color:#fff;font-family:inherit;">
    <div style="text-align:center;max-width:400px;padding:24px;">
      <h2 style="font-size:24px;margin:0 0 12px;">Age Verification Required</h2>
      <p style="color:#aaa;margin:0 0 24px;">${escapeHtml(page.age_gate_message || "This page contains 18+ content. You must be 18 or older to view it.")}</p>
      <div style="display:flex;gap:12px;justify-content:center;">
        <button onclick="document.getElementById('age-gate').style.display='none';sessionStorage.setItem('age_verified_${escapeHtml(page.id)}','1')" style="padding:12px 32px;border-radius:8px;border:none;background:#fff;color:#000;font-size:16px;cursor:pointer;font-weight:600;">I am 18+</button>
        <button onclick="window.location.href='https://google.com'" style="padding:12px 32px;border-radius:8px;border:none;background:#333;color:#fff;font-size:16px;cursor:pointer;">Leave</button>
      </div>
    </div>
  </div>
  <script nonce="${nonce}">
    if (sessionStorage.getItem('age_verified_${escapeHtml(page.id)}')) {
      var ag = document.getElementById('age-gate');
      if (ag) ag.style.display = 'none';
    }
  </script>
  `
      : ""
  }
</body>
</html>`;

  // Link Hot-Swap: no edge cache — link changes are live immediately.
  // Supabase query is <50ms; freshness matters more than cache hit rate
  // for low-volume, high-value conversion pages.
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.setHeader(
    "Content-Security-Policy",
    `default-src 'self'; ${scriptSrc}; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; ${imgSrc}; ${connectSrc}; frame-ancestors 'none'; base-uri 'self'`,
  );
  res.setHeader("Cache-Control", "private, no-cache");
  return res.status(200).send(html);
}
