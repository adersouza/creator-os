
import { Info } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/Tooltip';

/**
 * MetricInfo — the shared affordance that lets the operator (and a client
 * stakeholder opening a shared report) learn what a metric actually means,
 * without having to hunt the docs.
 *
 * Paired specifically with the differentiated metrics CLAUDE.md defines:
 *   EQS, Conversation Depth Score, Sends+Saves, Reply Chain Depth, etc.
 *
 * Progressive disclosure: the glyph is hidden by default and fades in when
 * the parent card is hovered or focused. Apply the `.metric-info-host`
 * utility to the card/container to opt in; otherwise the glyph is always
 * visible (legacy behavior). Also reveals on keyboard focus of the button
 * itself so screen-reader / keyboard-only users can still reach the help.
 *
 * Assumes a single <TooltipProvider> at the app root (Layout.tsx) so all
 * instances share one delayDuration state.
 */
export function MetricInfo({
  label,
  definition,
  className,
}: {
  label: string;
  definition: string;
  className?: string | undefined;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={`What is ${label}?`}
          className={`metric-info-glyph inline-flex items-center justify-center h-3.5 w-3.5 rounded-full text-muted-foreground hover:text-muted-foreground transition-[opacity,color] duration-150 outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)] ${className ?? ''}`}
        >
          <Info className="w-3 h-3" aria-hidden="true" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-[260px] leading-snug">
        {definition}
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * Canonical definitions for the metrics CLAUDE.md treats as differentiated.
 * Single source of truth — don't inline strings at call sites.
 */
export const METRIC_DEFINITIONS = {
  eqs:
    'Engagement Quality Score weights Sends 5×, Saves 3×, Comments 2×, Likes 1×. Higher means better discovery-signal engagement.',
  sendsPlusSaves:
    'Sends + Saves are the Mosseri-confirmed discovery metrics — the two actions that matter most for IG reach and Threads surfacing.',
  reach: 'Unique accounts your posts reached in the window.',
  followerGrowthPct: 'Follower growth rate, not raw count — normalizes small vs large accounts.',
  scheduleCompliance: 'Published ÷ scheduled — what share of planned posts actually went live.',
  postCount: 'Total posts published in the selected window across all connected accounts.',
  conversationDepth:
    'Conversation Depth Score tracks how many Threads replies chain ≥4 turns. Deeper threads signal genuine community.',
  replyVelocity: 'Median time between your reply and the next reply in a Threads chain.',
  nonFollowerViewPct:
    'Share of Threads views from non-followers. >40% means the post is landing on the For You feed.',
  reelsWatchTime: 'Average watch time on Reels. The primary retention signal IG weights for reach.',
} as const;

export type MetricKey = keyof typeof METRIC_DEFINITIONS;
