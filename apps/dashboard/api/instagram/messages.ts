/**
 * Instagram Messages — standalone route file
 *
 * This must remain as a separate file (not consolidated into api/instagram.ts)
 * because the messages handler uses its own ?action= sub-routing
 * (conversations, messages, send, etc.) which conflicts with the Vercel
 * rewrite that maps /api/instagram/:action → /api/instagram?action=:action.
 *
 * Vercel filesystem routes take priority over rewrites, so this file
 * ensures /api/instagram/messages?action=X reaches the handler directly.
 */

export { default } from "../_lib/handlers/instagram/messages.js";
