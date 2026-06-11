import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeftRight, Database, X } from 'lucide-react';
import { IconTooltipButton } from '@/components/ui/IconTooltipButton';
import { subscribe } from '@/services/realtimeManager';
import { supabase } from '@/services/supabase';
import type { Post } from './shared';
import { formatHour, DAY_NAMES_LONG } from './shared';

interface DbPostRow {
  id: string;
  content: string | null;
  status: string | null;
  scheduled_for: string | null;
  updated_at: string | null;
}

export function DBSyncVisualizer({
  open,
  posts,
  onClose,
}: {
  open: boolean;
  posts: Post[];
  onClose: () => void;
}) {
  const [rows, setRows] = useState<DbPostRow[]>([]);
  const [live, setLive] = useState(false);
  const [pulse, setPulse] = useState(false);
  const pulseTimerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const load = async () => {
      const { data } = await supabase
        .from('posts')
        .select('id,content,status,scheduled_for,updated_at')
        .order('updated_at', { ascending: false })
        .limit(30);
      if (!cancelled) setRows((data ?? []) as DbPostRow[]);
    };
    void load();
    const unsubscribe = subscribe(
      'calendar-sync-visualizer:posts',
      () =>
        supabase
          .channel('calendar-sync-visualizer:posts')
          .on('postgres_changes', { event: '*', schema: 'public', table: 'posts' }, () => {
            setPulse(true);
            if (pulseTimerRef.current) {
              window.clearTimeout(pulseTimerRef.current);
            }
            pulseTimerRef.current = window.setTimeout(() => {
              setPulse(false);
              pulseTimerRef.current = null;
            }, 800);
            void load();
          })
          .subscribe((status) => setLive(status === 'SUBSCRIBED')),
      load,
    );
    return () => {
      cancelled = true;
      if (pulseTimerRef.current) {
        window.clearTimeout(pulseTimerRef.current);
        pulseTimerRef.current = null;
      }
      unsubscribe();
      setLive(false);
    };
  }, [open]);

  const calendarById = useMemo(() => new Map(posts.map((post) => [post.id, post])), [posts]);

  if (!open) return null;

  return (
    <aside
      className="fixed inset-x-6 bottom-6 z-[80] overflow-hidden rounded-lg border border-border bg-card shadow-2xl"
    >
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-muted-foreground" />
          <div className="text-sm font-semibold text-foreground">DB sync visualizer</div>
          <span className={`rounded-full px-2 py-0.5 text-[0.625rem] font-bold uppercase tracking-[0.1em] ${live ? 'bg-[color-mix(in_srgb,var(--color-health-good)_16%,transparent)] text-[var(--color-health-good)]' : 'bg-muted text-muted-foreground'}`}>
            {live ? 'connected' : 'polling'}
          </span>
        </div>
        <IconTooltipButton label="Close sync visualizer" onClick={onClose}>
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground">
            <X className="h-4 w-4" />
          </span>
        </IconTooltipButton>
      </div>

      <div className="grid max-h-[420px] grid-cols-[1fr_56px_1fr] overflow-hidden">
        <div className="overflow-y-auto p-3">
          <div className="mb-2 text-[0.6875rem] font-bold uppercase tracking-[0.12em] text-muted-foreground">posts rows</div>
          {rows.map((row) => (
            <div key={row.id} className="mb-2 rounded-md border border-border bg-background p-2">
              <div className="truncate text-xs font-medium text-foreground">{row.content || 'Untitled'}</div>
              <div className="mt-1 font-mono text-[0.6875rem] text-muted-foreground">{row.status} · {row.scheduled_for ? new Date(row.scheduled_for).toLocaleString() : 'unscheduled'}</div>
            </div>
          ))}
        </div>
        <div className="flex items-center justify-center border-x border-border">
          <ArrowLeftRight className={`h-5 w-5 text-muted-foreground transition-transform ${pulse ? 'scale-125 text-[var(--color-oxblood)]' : ''}`} />
        </div>
        <div className="overflow-y-auto p-3">
          <div className="mb-2 text-[0.6875rem] font-bold uppercase tracking-[0.12em] text-muted-foreground">calendar bubbles</div>
          {rows.map((row) => {
            const post = calendarById.get(row.id);
            return (
              <div key={row.id} className="mb-2 rounded-md border border-border bg-background p-2">
                {post ? (
                  <>
                    <div className="truncate text-xs font-medium text-foreground">{post.title}</div>
                    <div className="mt-1 font-mono text-[0.6875rem] text-muted-foreground">
                      {DAY_NAMES_LONG[post.day]} · {formatHour(post.hour, post.minute)} · {post.account}
                    </div>
                  </>
                ) : (
                  <div className="text-xs text-muted-foreground">Not in current filtered calendar view</div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </aside>
  );
}
