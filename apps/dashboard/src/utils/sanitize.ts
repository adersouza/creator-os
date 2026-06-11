/**
 * Content Sanitization Utilities
 * Prevents XSS attacks by sanitizing user-generated content
 */

import DOMPurify from "isomorphic-dompurify";
import logger from "./logger.js";

/**
 * Sanitize text content (strip all HTML tags and scripts)
 * Use this for user-generated text content like post content
 */
export function sanitizeText(content: string): string {
  if (!content) return "";

  // Strip all HTML tags and scripts
  return DOMPurify.sanitize(content, {
    ALLOWED_TAGS: [], // No HTML tags allowed
    ALLOWED_ATTR: [], // No attributes allowed
    KEEP_CONTENT: true, // Keep text content
  });
}

/**
 * Sanitize HTML content (allow safe HTML tags only)
 * Use this for rich text editors where some formatting is allowed
 */
export function sanitizeHTML(content: string): string {
  if (!content) return "";

  // Allow only safe HTML tags
  return DOMPurify.sanitize(content, {
    ALLOWED_TAGS: ["b", "i", "em", "strong", "a", "p", "br"],
    ALLOWED_ATTR: ["href", "target"],
    ALLOW_DATA_ATTR: false,
  });
}

/**
 * Sanitize URL to prevent javascript: and data: URIs
 */
export function sanitizeURL(url: string): string {
  if (!url) return "";

  const trimmed = url.trim().toLowerCase();

  // Block dangerous protocols
  if (
    trimmed.startsWith("javascript:") ||
    trimmed.startsWith("data:") ||
    trimmed.startsWith("vbscript:") ||
    trimmed.startsWith("file:")
  ) {
    logger.warn("Blocked dangerous URL:", url);
    return "";
  }

  // Ensure it's a valid HTTP(S) URL
  try {
    const parsed = new URL(url);
    if (!["http:", "https:"].includes(parsed.protocol)) {
      logger.warn("Invalid URL protocol:", url);
      return "";
    }
    return parsed.href; // Return canonical form to prevent encoding tricks
  } catch {
    // Not a valid absolute URL — only allow relative paths without protocol-like patterns
    if (/^[a-z]+:/i.test(url.trim())) return "";
    return url;
  }
}

/**
 * Validate and sanitize post content
 * Returns sanitized content or throws error if invalid
 */
export function validatePostContent(content: string): string {
  if (!content || content.trim().length === 0) {
    throw new Error("Post content cannot be empty");
  }

  const sanitized = sanitizeText(content);

  if (sanitized.length > 500) {
    throw new Error("Post content must be 500 characters or less");
  }

  return sanitized;
}

/**
 * Sanitize media URLs array
 */
export function sanitizeMediaURLs(urls: string[]): string[] {
  if (!urls || urls.length === 0) return [];

  return urls.map(sanitizeURL).filter((url) => url !== ""); // Remove invalid URLs
}

/**
 * Validate a post-auth redirect path and return a safe value.
 * Only same-origin relative paths are allowed — rejects protocol-relative
 * URLs (`//evil.com`), absolute URLs, and control-char injection.
 * Returns the given fallback (default `/dashboard`) when the input is unsafe.
 */
export function safeRedirectPath(path: unknown, fallback = "/dashboard"): string {
  if (typeof path !== "string") return fallback;
  const trimmed = path.trim();
  if (!trimmed.startsWith("/")) return fallback;
  if (trimmed.startsWith("//") || trimmed.startsWith("/\\")) return fallback;
  if (/[\r\n\t\0]/.test(trimmed)) return fallback;
  return trimmed;
}
