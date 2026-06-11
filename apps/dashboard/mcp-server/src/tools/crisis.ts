import type { ToolRegistrar } from "../helpers.js";
import { api, respond } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "get_crisis_status",
    "[SAFETY] Check for active crisis events — engagement crashes, shadowbans, or viral negative mentions. Returns active crises, recently resolved (last 7 days), and current severity level (normal/warning/severe). Run this periodically to catch problems early.",
    {},
    async () => respond(await api("/agent?action=crisis-status"))
  );
};
