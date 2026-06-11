// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/* =========================================================================
   Analytics shared types, constants, and helpers.
   ========================================================================= */

export type Platform = "all" | "threads" | "ig";
export type Timeframe = "7" | "30" | "90";
export type ScopedAccountLite = {
  id?: string | null | undefined;
  handle: string;
  groupColor: string;
  platform: "threads" | "instagram";
} | null;

export const platforms: { id: Platform; label: string }[] = [
  { id: "all", label: "All" },
  { id: "threads", label: "Threads" },
  { id: "ig", label: "Instagram" },
];

export const timeframes: { id: Timeframe; label: string }[] = [
  { id: "7", label: "7d" },
  { id: "30", label: "30d" },
  { id: "90", label: "90d" },
];

export const TIMEFRAME_META: Record<Timeframe, { label: string }> = {
  "7": { label: "7d" },
  "30": { label: "30d" },
  "90": { label: "90d" },
};

/* -------------------------------------------------------------------------
   HERO METRICS — type only; values computed live in Analytics.tsx
   ------------------------------------------------------------------------- */
export interface HeroMetric {
  label: string;
  value: string;
  suffix?: string | undefined;
  delta: string;
  deltaDir: "up" | "down" | "neutral";
  spark: number[];
}

/* -------------------------------------------------------------------------
   CONTENT LIFESPAN — industry benchmark decay curves (intentional reference data)
   Retained for analytics panels that compare content decay curves.
   ------------------------------------------------------------------------- */
export interface LifespanCurve {
  type: string;
  color: string;
  halfLifeHours: number;
  points: number[];
}
export const LIFESPANS: Record<Platform, LifespanCurve[]> = {
  all: [
    {
      type: "IG Reels",
      color: "var(--color-chart-ink)",
      halfLifeHours: 18,
      points: [8, 22, 36, 48, 58, 68, 75, 82, 87, 91, 94, 96, 98, 99, 100],
    },
    {
      type: "Threads text",
      color: "var(--color-muted-foreground)",
      halfLifeHours: 4,
      points: [22, 44, 62, 74, 83, 89, 93, 96, 97, 98, 99, 99, 100, 100, 100],
    },
    {
      type: "IG Carousels",
      color:
        "color-mix(in srgb, var(--color-muted-foreground) 58%, transparent)",
      halfLifeHours: 28,
      points: [5, 14, 22, 32, 42, 52, 61, 68, 75, 81, 86, 90, 94, 97, 100],
    },
    {
      type: "IG Stories",
      color: "var(--color-harbor)",
      halfLifeHours: 8,
      points: [
        18, 40, 60, 75, 86, 93, 97, 99, 100, 100, 100, 100, 100, 100, 100,
      ],
    },
  ],
  threads: [
    {
      type: "Text-only",
      color: "var(--color-chart-ink)",
      halfLifeHours: 4,
      points: [22, 44, 62, 74, 83, 89, 93, 96, 97, 98, 99, 99, 100, 100, 100],
    },
    {
      type: "Image post",
      color: "var(--color-muted-foreground)",
      halfLifeHours: 6,
      points: [16, 34, 52, 66, 76, 84, 90, 94, 96, 98, 99, 99, 100, 100, 100],
    },
    {
      type: "Carousel",
      color:
        "color-mix(in srgb, var(--color-muted-foreground) 58%, transparent)",
      halfLifeHours: 10,
      points: [10, 24, 40, 54, 66, 76, 83, 89, 93, 96, 98, 99, 99, 100, 100],
    },
  ],
  ig: [
    {
      type: "Reels",
      color: "var(--color-chart-ink)",
      halfLifeHours: 18,
      points: [8, 22, 36, 48, 58, 68, 75, 82, 87, 91, 94, 96, 98, 99, 100],
    },
    {
      type: "Carousels",
      color: "var(--color-muted-foreground)",
      halfLifeHours: 28,
      points: [5, 14, 22, 32, 42, 52, 61, 68, 75, 81, 86, 90, 94, 97, 100],
    },
    {
      type: "Stories",
      color:
        "color-mix(in srgb, var(--color-muted-foreground) 58%, transparent)",
      halfLifeHours: 8,
      points: [
        18, 40, 60, 75, 86, 93, 97, 99, 100, 100, 100, 100, 100, 100, 100,
      ],
    },
    {
      type: "Feed (single)",
      color: "var(--color-harbor)",
      halfLifeHours: 14,
      points: [10, 24, 38, 50, 61, 70, 78, 84, 89, 92, 95, 97, 99, 99, 100],
    },
  ],
};
export const LIFESPAN_HOURS = [
  0, 1, 2, 4, 6, 8, 12, 18, 24, 36, 48, 72, 96, 120, 168,
];

/* -------------------------------------------------------------------------
   POSTING HEATMAP
   ------------------------------------------------------------------------- */
export const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/* =========================================================================
   HELPERS
   ========================================================================= */
export function parseValue(str: string): {
  num: number;
  unit: string;
  decimals: number;
} {
  const m = str.match(/^([-+]?[\d,.]+)(.*)$/);
  if (!m) return { num: 0, unit: str, decimals: 0 };
  const numStr = m[1]!.replace(/,/g, "");
  const decimals = numStr.includes(".") ? 1 : 0;
  return { num: parseFloat(numStr), unit: m[2]!, decimals };
}

export function getEffectivePlatform(
  platform: Platform,
  scopedAccount: ScopedAccountLite,
): Platform {
  if (!scopedAccount) return platform;
  return scopedAccount.platform === "instagram" ? "ig" : "threads";
}

/* -------------------------------------------------------------------------
   FleetMetrics key adapters (for mobile views).
   ------------------------------------------------------------------------- */
import type {
  FleetMetricsTimeframe,
  FleetMetricsPlatform,
} from "@/hooks/useFleetMetrics";

export function formatCompact(n: number): string {
  if (n >= 1_000_000)
    return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, "")}K`;
  return Math.round(n).toString();
}

export function toFleetTimeframe(t: Timeframe): FleetMetricsTimeframe {
  return t === "7" ? "7d" : t === "30" ? "30d" : "90d";
}
/** v2 path: thread the real day count instead of bucketing into 7/30/90. */
export function daysToFleetTimeframe(days: number): FleetMetricsTimeframe {
  if (days === 7) return "7d";
  if (days === 14) return "14d";
  if (days === 30) return "30d";
  if (days === 90) return "90d";
  return { days };
}
/** Closest legacy enum for widgets that haven't yet been ported to day count. */
export function daysToLegacyTimeframe(days: number): Timeframe {
  if (days <= 10) return "7";
  if (days <= 45) return "30";
  return "90";
}
export function toFleetPlatform(p: Platform): FleetMetricsPlatform {
  return p === "ig" ? "instagram" : p;
}
