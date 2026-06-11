import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, zBool } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "get_agency_branding",
    "[BRANDING] Get current agency branding settings (name, logo URL, brand color). Agency tier required.",
    {},
    async () => respond(await api("/user?action=branding"))
  );

  server.tool(
    "update_agency_branding",
    "[BRANDING] Update agency white-label branding — name, brand color, and logo. Agency tier required.",
    {
      agencyName: z.string().optional().describe("Agency display name (max 200 chars)"),
      brandColor: z.string().optional().describe("Brand hex color (e.g. '#6366f1')"),
      removeLogo: zBool.optional().describe("Set to true to remove the current logo"),
    },
    async ({ agencyName, brandColor, removeLogo }) => {
      return respond(await api("/user?action=branding", "POST", {
        agency_name: agencyName,
        brand_color: brandColor,
        remove_logo: removeLogo,
      }));
    }
  );
};
