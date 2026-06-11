import type { ToolRegistrar } from "../helpers.js";
import { api, respond } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "get_referral_info",
    "[REFERRALS] Get your referral code, link, and referral count. If no code exists, use get_referral_stats to see if one needs to be created.",
    {},
    async () => respond(await api("/referrals"))
  );

  server.tool(
    "get_referral_stats",
    "[REFERRALS] Get detailed referral statistics — referral codes, all referrals, completion rates, and reward months earned/used/available.",
    {},
    async () => respond(await api("/referrals?action=stats", "POST", {}))
  );
};
