#!/usr/bin/env node

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { AUTH_TOKEN } from "./helpers.js";
import { installOperatorControlPlane } from "./operatorControlPlane.js";
import { LOCAL_TOOL_MODULES } from "./toolModules.js";

// -- Auth check --
if (!AUTH_TOKEN) {
  console.error(
    "[threadsdashboard-mcp] TD_AUTH_TOKEN env var is required. Set it to a valid Supabase JWT."
  );
  process.exit(1);
}

// -- Server --
const server = new McpServer({
  name: "threadsdashboard",
  version: "2.0.0",
});

installOperatorControlPlane(server);

// -- Register all tools --
for (const register of LOCAL_TOOL_MODULES) {
  register(server);
}

// -- Start --
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error(`[threadsdashboard-mcp] Server started — ${LOCAL_TOOL_MODULES.length} modules loaded`);
}

main().catch((err) => {
  console.error("[threadsdashboard-mcp] Fatal:", err);
  process.exit(1);
});
