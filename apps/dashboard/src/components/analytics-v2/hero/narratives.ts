// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import type { AnalyticsPlatform } from '@/lib/analyticsUrlState';

/**
 * Hardcoded v1 narrative strings per spec §12. In Wave 2 these are swapped
 * for LLM output from cross-insights + reach-anomaly. Tokens like {{REACH_DELTA}}
 * are filled with real fleet numbers at render time so the prose stays
 * truthful even while the copy is static.
 *
 * Body segments are an alternating array of plain strings and evidence-link
 * objects — the renderer walks the array and wraps evidence items in a span
 * that scrolls to #evidence-{n} on click (spec §3.2).
 */

export interface EvidenceLink {
  kind: 'ev';
  text: string;
  /** Footnote number — maps to #evidence-N anchor + footnote superscript. */
  n: number;
}

export type NarrativeSegment = string | EvidenceLink;

export interface NarrativeTemplate {
  /** Eyebrow above the headline. */
  eyebrow: string;
  /** Headline with {{tokens}}. Oxblood emphasis is applied by the renderer. */
  headline: string;
  /** Body paragraph as segments. */
  body: NarrativeSegment[];
}

export const NARRATIVES: Record<AnalyticsPlatform, NarrativeTemplate> = {
  all: {
    eyebrow: 'Investigation brief',
    headline:
      'Reach moved **{{REACH_DELTA}}** this period across **{{AT_RISK_COUNT}} accounts** flagged at risk fleet-wide.',
    body: [
      'Review the ',
      { kind: 'ev', text: 'fleet grid', n: 1 },
      ' to identify which accounts are driving the shift. Check the ',
      { kind: 'ev', text: 'discovery source breakdown', n: 2 },
      ' for surface-level signals, and the ',
      { kind: 'ev', text: 'format report', n: 3 },
      ' to see which content types are holding reach across your fleet.',
    ],
  },
  ig: {
    eyebrow: 'Investigation brief',
    headline:
      'IG reach moved **{{REACH_DELTA}}** this period with **{{AT_RISK_COUNT}} accounts** showing at-risk engagement scores.',
    body: [
      'Check the ',
      { kind: 'ev', text: 'non-follower reach trend', n: 1 },
      ' to see if Explore-surface discovery is driving the change. The ',
      { kind: 'ev', text: 'originality status', n: 5 },
      ' for accounts at risk may reveal suppression triggers. Use the ',
      { kind: 'ev', text: 'format report', n: 3 },
      ' to confirm which content types are maintaining reach across your fleet.',
    ],
  },
  threads: {
    eyebrow: 'Investigation brief',
    headline:
      'Threads views moved **{{REACH_DELTA}}** this period — **{{AT_RISK_COUNT}} accounts** across your fleet warrant closer review.',
    body: [
      'Check the ',
      { kind: 'ev', text: 'source breakdown', n: 2 },
      ' to see whether home-feed or search-surface discovery is shifting. Review ',
      { kind: 'ev', text: 'ghost posts', n: 5 },
      ' (low-view posts after 24h) for suppression signals, and the ',
      { kind: 'ev', text: 'reply depth report', n: 9 },
      ' to assess conversation quality across your fleet.',
    ],
  },
};

export function fillTokens(
  template: string,
  tokens: Record<string, string>,
): string {
  return template.replace(/\{\{(\w+)\}\}/g, (_, key) => tokens[key] ?? `{{${key}}}`);
}

/**
 * Render ``**bold**`` markers as oxblood-accented strong spans.
 * Returns ReactNode[] suitable for spreading into a JSX element.
 */
export function renderEmphasized(text: string): Array<{ kind: 'plain' | 'bold'; text: string }> {
  const out: Array<{ kind: 'plain' | 'bold'; text: string }> = [];
  const re = /\*\*([^*]+)\*\*/g;
  let last = 0;
  let match = re.exec(text);
  while (match !== null) {
    if (match.index > last) out.push({ kind: 'plain', text: text.slice(last, match.index) });
    out.push({ kind: 'bold', text: match[1]! });
    last = match.index + match[0].length;
    match = re.exec(text);
  }
  if (last < text.length) out.push({ kind: 'plain', text: text.slice(last) });
  return out;
}
