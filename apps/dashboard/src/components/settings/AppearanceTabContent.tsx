import { useEffect, useState } from 'react';
import { Sun, Moon, Monitor, CheckCircle2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { SectionHeader, Panel } from './shared';
import { Button } from '@/components/ui/Button';
import {
  loadThemeFromRemote,
  persistThemeToRemote,
  applyThemeChoice,
  readThemeChoiceFromStorage,
  type ThemeChoice,
  persistPaletteToRemote,
} from '@/lib/themeSync';

export function AppearanceTab() {
  const [choice, setChoice] = useState<ThemeChoice>(() => readThemeChoiceFromStorage());

  // Hydrate from user_settings once on mount so signed-in users see the choice
  // they made on another device. localStorage stays as the fast-path cache.
  // biome-ignore lint/correctness/useExhaustiveDependencies: applyTheme intentionally omitted — adding it causes infinite re-renders
  useEffect(() => {
    let cancelled = false;
    void loadThemeFromRemote().then((remote) => {
      if (cancelled || !remote) return;
      applyTheme(remote, { persistRemote: false });
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const applyTheme = (c: ThemeChoice, opts: { persistRemote?: boolean | undefined } = {}) => {
    const { persistRemote = true } = opts;
    applyThemeChoice(c);
    setChoice(c);
    if (persistRemote) void persistThemeToRemote(c);
  };

  useEffect(() => {
    const root = document.documentElement;
    const legacyPalette = root.getAttribute('data-theme') || localStorage.getItem('juno33-palette');

    root.removeAttribute('data-theme');
    try {
      localStorage.removeItem('juno33-palette');
    } catch {
      /* ignore */
    }

    if (legacyPalette) void persistPaletteToRemote('juno');
  }, []);

  const themeOptions: { id: ThemeChoice; label: string; Icon: typeof Sun; preview: 'light' | 'dark' }[] = [
    { id: 'light', label: 'Light', Icon: Sun, preview: 'light' },
    { id: 'dark', label: 'Dark', Icon: Moon, preview: 'dark' },
    { id: 'system', label: 'System', Icon: Monitor, preview: 'dark' },
  ];

  return (
    <div className="flex flex-col gap-6">
      <SectionHeader
        title="Appearance"
        description="Choose light, dark, or system mode. The color family is locked to Nova/zinc with Juno oxblood so the product stays consistent."
      />

      <Panel>
        <div className="text-[0.6875rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground mb-3">
          Theme
        </div>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
          {themeOptions.map((opt) => {
            const active = choice === opt.id;
            return (
              <Button
                key={opt.id}
                variant="ghost"
                type="button"
                onClick={() => applyTheme(opt.id)}
                aria-pressed={active}
                className={cn(
                  'relative h-auto rounded-xl border p-0 transition-all text-left overflow-hidden',
                  'outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood-strong)]',
                  active
                    ? 'border-[color:var(--color-oxblood)]'
                    : 'border-border hover:border-ring/30',
                )}
              >
                <ThemePreview kind={opt.preview} />
                <div className="flex items-center justify-between gap-2 px-3 py-2.5 border-t border-border bg-card">
                  <div className="flex items-center gap-1.5 text-[0.78125rem] font-medium text-foreground">
                    <opt.Icon className="w-3.5 h-3.5 text-muted-foreground" />
                    {opt.label}
                  </div>
                  {active && (
                    <span
                      className="w-4 h-4 rounded-full flex items-center justify-center"
                      style={{ backgroundColor: 'var(--color-oxblood)' }}
                    >
                      <CheckCircle2 className="w-3 h-3 text-white" />
                    </span>
                  )}
                </div>
              </Button>
            );
          })}
        </div>
        <div className="text-[0.6875rem] text-muted-foreground mt-4">
          Theme respects your OS preference when set to System. Toggle any time from the sidebar.
        </div>
      </Panel>

      <Panel>
        <div className="text-[0.6875rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground mb-3">
          Palette locked
        </div>
        <div className="rounded-xl border border-border bg-muted/50 p-4">
          <div className="text-[0.8125rem] font-medium text-foreground">
            Nova/zinc + Juno oxblood
          </div>
          <div className="mt-1 text-[0.75rem] leading-relaxed text-muted-foreground">
            Alternate legacy palettes are disabled so light mode, dark mode, charts, cards, and previews all match the shadcn Nova preset.
          </div>
        </div>
        <div className="text-[0.6875rem] text-muted-foreground mt-4">
          The sidebar theme toggle still switches light and dark instantly; only the brand palette is fixed.
        </div>
      </Panel>
    </div>
  );
}

function ThemePreview({ kind }: { kind: 'light' | 'dark' }) {
  const isDark = kind === 'dark';
  return (
    <div
      className="h-[108px] relative overflow-hidden"
      style={{
        background: isDark ? 'oklch(0.141 0.005 285.823)' : 'oklch(0.967 0.001 286.375)',
      }}
    >
      {/* Fake sidebar */}
      <div
        className="absolute left-2 top-2 bottom-2 w-[40px] rounded-md"
        style={{
          background: isDark ? 'oklch(0.21 0.006 285.885)' : 'oklch(0.985 0 0)',
          border: isDark ? '1px solid oklch(1 0 0 / 10%)' : '1px solid oklch(0.92 0.004 286.32)',
        }}
      />
      {/* Fake card */}
      <div
        className="absolute left-[52px] right-3 top-3 h-[44px] rounded-md flex items-center px-2 gap-1.5"
        style={{
          background: isDark ? 'oklch(0.21 0.006 285.885)' : 'oklch(1 0 0)',
          border: isDark ? '1px solid oklch(1 0 0 / 10%)' : '1px solid oklch(0.92 0.004 286.32)',
        }}
      >
        <span
          className="w-1.5 h-1.5 rounded-full"
          style={{ background: 'var(--color-oxblood)' }}
        />
        <span
          className="h-[5px] flex-1 rounded-full"
          style={{ background: isDark ? 'oklch(1 0 0 / 15%)' : 'oklch(0.92 0.004 286.32)' }}
        />
      </div>
      {/* Fake metric */}
      <div
        className="absolute left-[52px] right-3 bottom-3 h-[36px] rounded-md px-2 py-1.5"
        style={{
          background: isDark ? 'oklch(0.21 0.006 285.885)' : 'oklch(1 0 0)',
          border: isDark ? '1px solid oklch(1 0 0 / 10%)' : '1px solid oklch(0.92 0.004 286.32)',
        }}
      >
        <div
          className="h-[4px] w-6 rounded-full mb-1"
          style={{ background: isDark ? 'oklch(0.705 0.015 286.067)' : 'oklch(0.552 0.016 285.938)' }}
        />
        <div
          className="h-[10px] w-14 rounded-sm"
          style={{ background: isDark ? 'oklch(0.985 0 0)' : 'oklch(0.141 0.005 285.823)' }}
        />
      </div>
    </div>
  );
}
