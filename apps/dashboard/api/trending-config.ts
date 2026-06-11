/**
 * Trending Config — standalone route file
 *
 * Must remain separate because the Vercel rewrite to /api/trends?action=config
 * drops the frontend's ?groupId= query param.
 */

export { default } from "./_lib/handlers/misc/trending-config.js";
