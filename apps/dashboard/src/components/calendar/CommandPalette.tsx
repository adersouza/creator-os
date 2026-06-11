// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useMemo, useState } from 'react';
import { CalendarClock, Check, Sparkles, X } from 'lucide-react';
import {
  Command,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/Command';
import { Button } from '@/components/ui/Button';
import type { CalendarCommandAction } from '@/types/publishingReadiness';
import type { Post } from './shared';
import { DAY_NAMES_LONG, formatHour } from './shared';

export interface CommandDiff {
  post: Post;
  next: Pick<Post, 'day' | 'hour' | 'minute'>;
  warnings?: string[] | undefined;
}

export interface CommandPreview {
  label: string;
  reason: string;
  diffs: CommandDiff[];
  fillGaps?: boolean | undefined;
  action?: CalendarCommandAction | undefined;
  llmReasoning?: string | undefined;
}

const WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];

function nextWeekdayIndex(text: string): number | null {
  const match = text.match(/\b(?:to|into|on|posts to)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/i)
    || text.match(/\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/i);
  if (!match) return null;
  const idx = WEEKDAYS.indexOf(match[1]!.toLowerCase());
  return idx >= 0 ? idx : null;
}

function filterPosts(text: string, posts: Post[]): Post[] {
  const weekdayMention = text.match(/\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/i);
  const accountMention = text.match(/@[\w.-]+|account[_\s-]*handle\s+([\w.-]+)/i);
  let selected = posts.filter((post) => post.status !== 'published');
  if (weekdayMention && !/\bto\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/i.test(text)) {
    const day = WEEKDAYS.indexOf(weekdayMention[1]!.toLowerCase());
    selected = selected.filter((post) => post.day === day);
  } else if (/thursday posts/i.test(text)) {
    selected = selected.filter((post) => post.day === 3);
  }
  if (accountMention) {
    const raw = (accountMention[0].startsWith('@') ? accountMention[0] : accountMention[1])!.replace(/^@/, '').toLowerCase();
    selected = selected.filter((post) => post.account.replace(/^@/, '').toLowerCase() === raw);
  }
  return selected;
}

export function parseCalendarCommand(text: string, posts: Post[]): CommandPreview | null {
  const normalized = text.trim().toLowerCase();
  if (!normalized) return null;

  if (/\bfill\s+gaps?\b/.test(normalized)) {
    return {
      label: 'Fill queue gaps',
      reason: 'Opens queue-fill for the current calendar group.',
      diffs: [],
      fillGaps: true,
    };
  }

  const actionMatch: Array<[RegExp, CalendarCommandAction, string, string]> = [
    [/\b(first post|wizard|start here|setup)\b/, 'open_first_post_wizard', 'Open first-post wizard', 'Starts the guided publishing setup flow.'],
    [/\b(readiness|fixes|account health|publishing health)\b/, 'open_readiness', 'Open readiness fixes', 'Shows setup actions for account, push, and publishing health.'],
    [/\b(schedule draft|draft to calendar|queue draft)\b/, 'schedule_draft', 'Schedule next draft', 'Moves the next draft to a recommended calendar slot without dragging.'],
    [/\b(duplicate|copy post|clone)\b/, 'duplicate_post', 'Duplicate a post', 'Duplicates the first matching visible post.'],
    [/\b(notify me|convert to notify|manual handoff)\b/, 'convert_to_notify', 'Convert draft to Notify Me', 'Opens Composer in Instagram Notify Me mode.'],
    [/\b(next best|best time|peak time)\b/, 'move_next_best_time', 'Move to next best time', 'Moves the first matching post to the next peak slot.'],
  ];
  for (const [pattern, action, label, reason] of actionMatch) {
    if (pattern.test(normalized)) return { label, reason, diffs: [], action };
  }

  const selected = filterPosts(normalized, posts);
  if (selected.length === 0) return null;

  const weekdayTarget = nextWeekdayIndex(normalized);
  if (/\b(push|move|reschedule)\b/.test(normalized) && weekdayTarget !== null) {
    const diffs = selected.map((post) => ({ post, next: { day: weekdayTarget, hour: post.hour, minute: post.minute } }));
    return {
      label: `Move ${selected.length} to ${DAY_NAMES_LONG[weekdayTarget]}`,
      reason: 'Matched weekday reschedule intent.',
      diffs,
    };
  }

  const relative = normalized.match(/\b(?:push|delay|move)\s+(?:by\s+)?(\d+)\s*(hour|hours|day|days)\b/);
  if (relative) {
    const amount = Number(relative[1]);
    const unit = relative[2]!.startsWith('hour') ? 'hour' : 'day';
    const diffs = selected.map((post) => {
      const totalMinutes = post.day * 24 * 60 + post.hour * 60 + post.minute + amount * (unit === 'hour' ? 60 : 24 * 60);
      const clamped = Math.max(0, Math.min(7 * 24 * 60 - 15, totalMinutes));
      return {
        post,
        next: {
          day: Math.floor(clamped / (24 * 60)),
          hour: Math.floor((clamped % (24 * 60)) / 60),
          minute: clamped % 60,
        },
      };
    });
    return {
      label: `Delay ${selected.length} by ${amount} ${unit}${amount === 1 ? '' : 's'}`,
      reason: 'Matched relative offset intent.',
      diffs,
    };
  }

  const timeOfDay = normalized.match(/\b(?:to|at)\s+(morning|afternoon|evening)\b/);
  if (timeOfDay) {
    const hour = timeOfDay[1] === 'morning' ? 9 : timeOfDay[1] === 'afternoon' ? 14 : 18;
    return {
      label: `Move ${selected.length} to ${timeOfDay[1]}`,
      reason: 'Matched account/time-of-day intent.',
      diffs: selected.map((post) => ({ post, next: { day: post.day, hour, minute: 0 } })),
    };
  }

  return null;
}

export function CommandPalette({
  open,
  posts,
  onOpenChange,
  onConfirm,
  onFillGaps,
  onParseComplex,
  getWarnings,
}: {
  open: boolean;
  posts: Post[];
  onOpenChange: (open: boolean) => void;
  onConfirm: (preview: CommandPreview) => Promise<void>;
  onFillGaps: () => void;
  onParseComplex?: (text: string) => Promise<CommandPreview | null> | undefined;
  getWarnings?: (diff: CommandDiff) => string[] | undefined;
}) {
  const [text, setText] = useState('');
  const [isCommitting, setIsCommitting] = useState(false);
  const [llmPreview, setLlmPreview] = useState<CommandPreview | null>(null);
  const regexPreview = useMemo(() => parseCalendarCommand(text, posts), [text, posts]);
  const rawPreview = regexPreview ?? llmPreview;
  const preview = useMemo(() => {
    if (!rawPreview || !getWarnings) return rawPreview;
    return {
      ...rawPreview,
      diffs: rawPreview.diffs.map((diff) => ({
        ...diff,
        warnings: diff.warnings ?? getWarnings(diff),
      })),
    };
  }, [rawPreview, getWarnings]);
  const accounts = useMemo(() => new Set(preview?.diffs.map((diff) => diff.post.account) ?? []).size, [preview]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[90] bg-black/72 px-4 pt-[12vh] backdrop-blur-[8px]"
      onMouseDown={() => onOpenChange(false)}
    >
      <div
        className="mx-auto w-full max-w-2xl overflow-hidden rounded-xl border border-border bg-card shadow-2xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border bg-card px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Sparkles className="h-4 w-4 text-muted-foreground" />
            Calendar command
          </div>
          <Button type="button" variant="ghost" size="icon" aria-label="Close command palette" onClick={() => onOpenChange(false)}>
            <X aria-hidden="true" />
          </Button>
        </div>

        <Command label="Calendar command palette" className="rounded-none bg-transparent">
          <CommandInput
            autoFocus
            value={text}
            onValueChange={(value) => {
              setText(value);
              setLlmPreview(null);
            }}
            placeholder="Push Thursday posts to Friday, delay 2 hours, reschedule @account to morning..."
            className="h-14 border-0 text-[0.9375rem] placeholder:text-muted-foreground"
          />
          <CommandList className="border-t border-border p-3">
            {!preview && (
              <CommandEmpty className="px-2 py-8 text-center text-sm text-muted-foreground">
                <div>Try “push Thursday posts to Friday” or “delay 2 hours”.</div>
                {onParseComplex && text.trim().length > 6 && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="mt-4"
                    onClick={async () => {
                      setIsCommitting(true);
                      try {
                        setLlmPreview((await onParseComplex(text)) ?? null);
                      } finally {
                        setIsCommitting(false);
                      }
                    }}
                  >
                    Parse with Gemini
                  </Button>
                )}
              </CommandEmpty>
            )}
            {preview && (
              <CommandItem value={preview.label} className="outline-none">
                <div className="w-full rounded-lg border border-border bg-muted/35 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                        <CalendarClock className="h-4 w-4 text-muted-foreground" />
                        {preview.label}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {preview.fillGaps || preview.action
                          ? preview.reason
                          : `${preview.diffs.length} posts · ${accounts} account${accounts === 1 ? '' : 's'} affected`}
                      </div>
                      {preview.llmReasoning && (
                        <div className="mt-1 text-xs text-muted-foreground">{preview.llmReasoning}</div>
                      )}
                    </div>
                    <Button
                      type="button"
                      disabled={isCommitting}
                      size="sm"
                      onClick={async () => {
                        setIsCommitting(true);
                        try {
                          if (preview.fillGaps) onFillGaps();
                          else await onConfirm(preview);
                          setText('');
                          onOpenChange(false);
                        } finally {
                          setIsCommitting(false);
                        }
                      }}
                    >
                      <Check data-icon="inline-start" />
                      Confirm
                    </Button>
                  </div>

                  {preview.diffs.length > 0 && (
                    <div className="mt-3 max-h-60 overflow-y-auto rounded-md border border-border bg-card">
                      {preview.diffs.slice(0, 12).map(({ post, next }) => (
                        <div key={post.id} className="grid grid-cols-[1fr_auto] gap-3 border-b border-border px-3 py-2 last:border-b-0">
                          <div className="min-w-0">
                            <div className="truncate text-xs font-medium text-foreground">{post.title}</div>
                            <div className="text-[0.6875rem] text-muted-foreground">{post.account}</div>
                          </div>
                          <div className="text-right">
                            <div className="font-mono text-[0.6875rem] text-muted-foreground">
                              {DAY_NAMES_LONG[post.day]!.slice(0, 3)} {formatHour(post.hour, post.minute)}
                              <span className="px-1.5 text-muted-foreground">→</span>
                              {DAY_NAMES_LONG[next.day]!.slice(0, 3)} {formatHour(next.hour, next.minute)}
                            </div>
                            {post.status !== 'scheduled' && (
                              <div className="mt-0.5 text-[0.625rem] font-semibold text-[var(--color-gold)]">
                                {post.status}
                              </div>
                            )}
                          </div>
                          {(preview.diffs.find((diff) => diff.post.id === post.id)?.warnings?.length ?? 0) > 0 && (
                            <div className="col-span-2 rounded bg-[color-mix(in_srgb,var(--color-oxblood)_7%,transparent)] px-2 py-1 text-[0.6875rem] text-[var(--color-oxblood)]">
                              {preview.diffs.find((diff) => diff.post.id === post.id)?.warnings?.join(' · ')}
                            </div>
                          )}
                        </div>
                      ))}
                      {preview.diffs.length > 12 && (
                        <div className="px-3 py-2 text-xs text-muted-foreground">+{preview.diffs.length - 12} more</div>
                      )}
                    </div>
                  )}
                </div>
              </CommandItem>
            )}
          </CommandList>
        </Command>
      </div>
    </div>
  );
}
