import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

import { register as accounts } from "./tools/accounts.js";
import { register as ai } from "./tools/ai.js";
import { register as analytics } from "./tools/analytics.js";
import { register as autoposter } from "./tools/autoposter.js";
import { register as benchmarks } from "./tools/benchmarks.js";
import { register as beta } from "./tools/beta.js";
import { register as branding } from "./tools/branding.js";
import { register as businessOps } from "./tools/business-ops.js";
import { register as calendar } from "./tools/calendar.js";
import { register as composer } from "./tools/composer.js";
import { register as competitors } from "./tools/competitors.js";
import { register as crisis } from "./tools/crisis.js";
import { register as developer } from "./tools/developer.js";
import { register as discovery } from "./tools/discovery.js";
import { register as groups } from "./tools/groups.js";
import { register as inbox } from "./tools/inbox.js";
import { register as influencerCollabs } from "./tools/influencer-collabs.js";
import { register as instagramFeatures } from "./tools/instagram-features.js";
import { register as links } from "./tools/links.js";
import { register as listening } from "./tools/listening.js";
import { register as media } from "./tools/media.js";
import { register as onboarding } from "./tools/onboarding.js";
import { register as operator } from "./tools/operator.js";
import { register as posts } from "./tools/posts.js";
import { register as push } from "./tools/push.js";
import { register as quickwins } from "./tools/quickwins.js";
import { register as referrals } from "./tools/referrals.js";
import { register as reports } from "./tools/reports.js";
import { register as savedViews } from "./tools/saved-views.js";
import { register as settings } from "./tools/settings.js";
import { register as smartLinks } from "./tools/smart-links.js";
import { register as strategy } from "./tools/strategy.js";
import { register as system } from "./tools/system.js";
import { register as tags } from "./tools/tags.js";
import { register as team } from "./tools/team.js";
import { register as trendingConfig } from "./tools/trending-config.js";
import { register as user } from "./tools/user.js";

export type ToolRegistrar = (server: McpServer) => void;

export const TOOL_MODULE_NAMES = [
  "accounts",
  "posts",
  "media",
  "ai",
  "analytics",
  "inbox",
  "competitors",
  "autoposter",
  "listening",
  "reports",
  "links",
  "team",
  "discovery",
  "quickwins",
  "system",
  "strategy",
  "groups",
  "smart-links",
  "benchmarks",
  "influencer-collabs",
  "referrals",
  "crisis",
  "branding",
  "trending-config",
  "instagram-features",
  "calendar",
  "composer",
  "saved-views",
  "tags",
  "settings",
  "user",
  "beta",
  "developer",
  "onboarding",
  "operator",
  "push",
  "business-ops",
] as const;

export const HOSTED_TOOL_MODULE_PATHS = TOOL_MODULE_NAMES.map(
  (name) => `../mcp-server/dist/tools/${name}.js`,
);

export const LOCAL_TOOL_MODULES: ToolRegistrar[] = [
  accounts,
  posts,
  media,
  ai,
  analytics,
  inbox,
  competitors,
  autoposter,
  listening,
  reports,
  links,
  team,
  discovery,
  quickwins,
  system,
  strategy,
  groups,
  smartLinks,
  benchmarks,
  influencerCollabs,
  referrals,
  crisis,
  branding,
  trendingConfig,
  instagramFeatures,
  calendar,
  composer,
  savedViews,
  tags,
  settings,
  user,
  beta,
  developer,
  onboarding,
  operator,
  push,
  businessOps,
];
