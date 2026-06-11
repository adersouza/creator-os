/**
 * Instagram Comments — standalone route file
 *
 * Must remain separate from api/instagram.ts because this handler uses
 * its own ?action= sub-routing which conflicts with the Vercel rewrite.
 */

export { default } from "../_lib/handlers/instagram/comments.js";
