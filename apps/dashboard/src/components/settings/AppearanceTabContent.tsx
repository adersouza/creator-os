import { useEffect, useState } from 'react';
import { Sun, Moon, Monitor, CheckCircle2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { SectionHeader, Panel } from './shared';
import { Button } from '@/components/ui/Button';
import {
  loadThemeFromRemote,
  persistThemeToRemote,
  type ThemeChoice,
  loadPaletteFromRemote,
  persistPaletteToRemote,
  type PaletteChoice,
} from '@/lib/themeSync';

export function AppearanceTab() {
  const [choice, setChoice] = useState<ThemeChoice>(() => {
    try {
      const stored = localStorage.getItem('juno33-theme');
      if (stored === 'dark' || stored === 'light') return stored;
    } catch {
      /* ignore */
    }
    return 'system';
  });
  const [palette, setPalette] = useState<PaletteChoice>(() => {
    try {
      const stored = localStorage.getItem('juno33-palette');
      const alts: PaletteChoice[] = ['neptune', 'apollo', 'mars', 'diana', 'vulcan', 'minerva'];
      if (alts.includes(stored as PaletteChoice)) return stored as PaletteChoice;
    } catch {
      /* ignore */
    }
    return 'juno';
  });

  // Hydrate from user_settings once on mount so signed-in users see the choice
  // they made on another device. localStorage stays as the fast-path cache.
  // biome-ignore lint/correctness/useExhaustiveDependencies: applyTheme intentionally omitted — adding it causes infinite re-renders
  useEffect(() => {
    let cancelled = false;
    void loadThemeFromRemote().then((remote) => {
      if (cancelled || !remote) return;
      applyTheme(remote, { persistRemote: false });
    });
    void loadPaletteFromRemote().then((remote) => {
      if (cancelled || !remote) return;
      applyPalette(remote, { persistRemote: false });
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const applyTheme = (c: ThemeChoice, opts: { persistRemote?: boolean | undefined } = {}) => {
    const { persistRemote = true } = opts;
    const root = document.documentElement;
    if (c === 'system') {
      try {
        localStorage.removeItem('juno33-theme');
      } catch {
        /* ignore */
      }
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      root.classList.toggle('dark', prefersDark);
    } else {
      root.classList.toggle('dark', c === 'dark');
      try {
        localStorage.setItem('juno33-theme', c);
      } catch {
        /* ignore */
      }
    }
    setChoice(c);
    if (persistRemote) void persistThemeToRemote(c);
  };

  const applyPalette = (p: PaletteChoice, opts: { persistRemote?: boolean | undefined } = {}) => {
    const { persistRemote = true } = opts;
    const root = document.documentElement;
    if (p === 'juno') {
      // Juno is the default — no attribute needed. Removing the attr keeps
      // the @theme {} block authoritative without specificity battles.
      root.removeAttribute('data-theme');
      try {
        localStorage.removeItem('juno33-palette');
      } catch {
        /* ignore */
      }
    } else {
      root.setAttribute('data-theme', p);
      try {
        localStorage.setItem('juno33-palette', p);
      } catch {
        /* ignore */
      }
    }
    setPalette(p);
    if (persistRemote) void persistPaletteToRemote(p);
  };

  const themeOptions: { id: ThemeChoice; label: string; Icon: typeof Sun; preview: 'light' | 'dark' }[] = [
    { id: 'light', label: 'Light', Icon: Sun, preview: 'light' },
    { id: 'dark', label: 'Dark', Icon: Moon, preview: 'dark' },
    { id: 'system', label: 'System', Icon: Monitor, preview: 'dark' },
  ];

  // Mars + Vulcan ship as theme files but are intentionally absent from the
  // picker — empirically they read as "shades of Juno" in light mode and
  // didn't earn the slot. Legacy localStorage values still resolve via
  // theme-init.js + PaletteChoice, so users who picked them previously keep
  // their setting. Re-add to this array to re-expose.
  const paletteOptions: { id: PaletteChoice; label: string; tagline: string }[] = [
    { id: 'juno', label: 'Juno', tagline: 'Oxblood + cream — the canonical brand' },
    { id: 'neptune', label: 'Neptune', tagline: 'Abyssal navy + Tiffany — cool counterpart' },
    { id: 'apollo', label: 'Apollo', tagline: 'Amber + warm gold — sunlit warmth' },
    { id: 'diana', label: 'Diana', tagline: 'Pine + sage — lunar contemplation' },
    { id: 'minerva', label: 'Minerva', tagline: 'Olive + warm gold — scholarly considered' },
  ];

  return (
    <div className="flex flex-col gap-6">
      <SectionHeader
        title="Appearance"
        description="Juno33 looks different in the morning than it does late at night. Pick whichever helps you focus."
      />

      <Panel>
        <div className="text-[0.6875rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground mb-3">
          Theme
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
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
          Palette
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {paletteOptions.map((opt) => {
            const active = palette === opt.id;
            return (
              <Button
                key={opt.id}
                variant="ghost"
                type="button"
                onClick={() => applyPalette(opt.id)}
                aria-pressed={active}
                className={cn(
                  'relative h-auto rounded-xl border p-0 transition-all text-left overflow-hidden',
                  'outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood-strong)]',
                  active
                    ? 'border-[color:var(--color-oxblood)]'
                    : 'border-border hover:border-ring/30',
                )}
              >
                <PalettePreview palette={opt.id} />
                <div className="flex items-center justify-between gap-2 px-3 py-2.5 border-t border-border bg-card">
                  <div>
                    <div className="text-[0.78125rem] font-medium text-foreground">{opt.label}</div>
                    <div className="text-[0.6875rem] text-muted-foreground mt-0.5">{opt.tagline}</div>
                  </div>
                  {active && (
                    <span
                      className="w-4 h-4 rounded-full flex items-center justify-center shrink-0"
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
          Palette is independent of light/dark — pick the brand color family. Status colors stay shared across both palettes.
        </div>
      </Panel>
    </div>
  );
}

/* Inline previews for the palette picker. The swatches show the brand-vs-tide
   pair for each palette so the picker reads as "what each option actually
   looks like" rather than just a name. Substrate gradients are simplified
   versions of the real body::before blobs, scaled to the 88px chip. */
type PalettePreviewSpec = {
  bg: string;          // light surface
  brand: string;
  tide: string;
  blob1: string;       // substrate atmosphere blob (top-left)
  blob2: string;       // substrate atmosphere blob (bottom-right)
  inkSoft: string;     // muted label color
  inkBrand: string;    // brand-ink for the hex caption
};

const PALETTE_PREVIEW: Record<PaletteChoice, PalettePreviewSpec> = {
  juno: {
    bg: '#F4F4F2',
    brand: '#E5484D',
    tide: '#B33A3F',
    blob1: 'color-mix(in srgb, #E5484D 14%, transparent)',
    blob2: 'color-mix(in_srgb,var(--color-foreground)_8%,transparent)',
    inkSoft: 'color-mix(in_srgb,var(--color-foreground)_55%,transparent)',
    inkBrand: '#E5484D',
  },
  neptune: {
    bg: '#E5EAEE',
    brand: '#0E2B3A',
    tide: '#0ABAB5',
    blob1: 'color-mix(in srgb, #0ABAB5 20%, transparent)',
    blob2: 'color-mix(in srgb, #5082A0 18%, transparent)',
    inkSoft: 'color-mix(in srgb, #0A1218 55%, transparent)',
    inkBrand: '#0E2B3A',
  },
  apollo: {
    bg: '#F5F1E8',
    brand: '#8C5A1A',
    tide: '#D89A2C',
    blob1: 'color-mix(in srgb, #F0DCA8 55%, transparent)',
    blob2: 'color-mix(in srgb, #E8C880 40%, transparent)',
    inkSoft: 'color-mix(in srgb, #1F1610 55%, transparent)',
    inkBrand: '#8C5A1A',
  },
  mars: {
    bg: '#ECE8E5',
    brand: '#8C2A2A',
    tide: '#C84040',
    blob1: 'color-mix(in srgb, #E8B8B8 40%, transparent)',
    blob2: 'color-mix(in srgb, #A8A8A8 30%, transparent)',
    inkSoft: 'color-mix(in srgb, #1A0E0E 55%, transparent)',
    inkBrand: '#8C2A2A',
  },
  diana: {
    bg: '#EDF0EC',
    brand: '#1F4D38',
    tide: '#5A8A6E',
    blob1: 'color-mix(in srgb, #A0C4A8 42%, transparent)',
    blob2: 'color-mix(in srgb, #A8B8C4 32%, transparent)',
    inkSoft: 'color-mix(in srgb, #0A1810 55%, transparent)',
    inkBrand: '#1F4D38',
  },
  vulcan: {
    bg: '#EDE8E2',
    brand: '#2A1810',
    tide: '#D8552A',
    blob1: 'color-mix(in srgb, #D8A884 40%, transparent)',
    blob2: 'color-mix(in srgb, #A89884 34%, transparent)',
    inkSoft: 'color-mix(in srgb, #1A0E08 55%, transparent)',
    inkBrand: '#2A1810',
  },
  minerva: {
    bg: '#EFEDE6',
    brand: '#5C6B3D',
    tide: '#A88838',
    blob1: 'color-mix(in srgb, #D8D8A8 42%, transparent)',
    blob2: 'color-mix(in srgb, #B8B8A8 34%, transparent)',
    inkSoft: 'color-mix(in srgb, #1A1810 55%, transparent)',
    inkBrand: '#5C6B3D',
  },
};

function PalettePreview({ palette }: { palette: PaletteChoice }) {
  const spec = PALETTE_PREVIEW[palette];
  return (
    <div
      className="h-[88px] relative overflow-hidden"
      style={{
        background: spec.bg,
        backgroundImage: `radial-gradient(circle at 22% 20%, ${spec.blob1} 0%, transparent 60%), radial-gradient(circle at 78% 70%, ${spec.blob2} 0%, transparent 55%)`,
      }}
    >
      <div className="absolute inset-3 flex items-center gap-2">
        <span
          className="w-9 h-9 rounded-lg shrink-0"
          style={{ background: spec.brand, boxShadow: `0 2px 8px ${spec.blob2}` }}
        />
        <span
          className="w-9 h-9 rounded-lg shrink-0"
          style={{ background: spec.tide, boxShadow: `0 2px 8px ${spec.blob1}` }}
        />
        <div className="ml-1 flex-1 min-w-0">
          <div
            className="text-[0.625rem] font-semibold uppercase tracking-[0.08em]"
            style={{ color: spec.inkSoft }}
          >
            Brand · Tide
          </div>
          <div className="font-mono text-[0.6875rem] mt-0.5 truncate" style={{ color: spec.inkBrand }}>
            {spec.brand} · {spec.tide}
          </div>
        </div>
      </div>
    </div>
  );
}

function ThemePreview({ kind }: { kind: 'light' | 'dark' }) {
  const isDark = kind === 'dark';
  return (
    <div
      className="h-[108px] relative overflow-hidden"
      style={{
        background: isDark ? '#0A0A0B' : '#F4F1E8',
        backgroundImage: isDark
          ? 'radial-gradient(circle at 70% 30%, color-mix(in srgb, var(--color-oxblood) 8%, transparent) 0%, transparent 60%)'
          : 'radial-gradient(circle at 20% 20%, color-mix(in srgb, #F0D4C4 90%, transparent) 0%, transparent 52%), radial-gradient(circle at 85% 70%, color-mix(in srgb, #D8C4E4 50%, transparent) 0%, transparent 55%)',
      }}
    >
      {/* Fake sidebar */}
      <div
        className="absolute left-2 top-2 bottom-2 w-[40px] rounded-md"
        style={{
          background: isDark ? 'color-mix(in srgb, #FFFFFF 4%, transparent)' : 'color-mix(in srgb, #FFFDF8 72%, transparent)',
          border: isDark ? '1px solid color-mix(in srgb, #FFFFFF 8%, transparent)' : '0.5px solid color-mix(in srgb, #0A0A0B 8%, transparent)',
          backdropFilter: 'blur(8px)',
          WebkitBackdropFilter: 'blur(8px)',
        }}
      />
      {/* Fake card */}
      <div
        className="absolute left-[52px] right-3 top-3 h-[44px] rounded-md flex items-center px-2 gap-1.5"
        style={{
          background: isDark ? 'color-mix(in srgb, #FFFFFF 6%, transparent)' : 'var(--color-card)',
          border: isDark ? '1px solid color-mix(in srgb, #FFFFFF 8%, transparent)' : '0.5px solid color-mix(in srgb, #0A0A0B 6%, transparent)',
          boxShadow: isDark ? 'none' : 'inset 0 1px 0 color-mix(in srgb, #FFFFFF 80%, transparent)',
        }}
      >
        <span
          className="w-1.5 h-1.5 rounded-full"
          style={{ background: 'var(--color-oxblood)' }}
        />
        <span
          className="h-[5px] flex-1 rounded-full"
          style={{ background: isDark ? 'color-mix(in srgb, #FFFFFF 12%, transparent)' : 'color-mix(in srgb, #0A0A0B 12%, transparent)' }}
        />
      </div>
      {/* Fake metric */}
      <div
        className="absolute left-[52px] right-3 bottom-3 h-[36px] rounded-md px-2 py-1.5"
        style={{
          background: isDark ? 'color-mix(in srgb, #FFFFFF 6%, transparent)' : 'var(--color-card)',
          border: isDark ? '1px solid color-mix(in srgb, #FFFFFF 8%, transparent)' : '0.5px solid color-mix(in srgb, #0A0A0B 6%, transparent)',
        }}
      >
        <div
          className="h-[4px] w-6 rounded-full mb-1"
          style={{ background: isDark ? 'color-mix(in srgb, #FAFAFA 35%, transparent)' : 'color-mix(in srgb, #0A0A0B 35%, transparent)' }}
        />
        <div
          className="h-[10px] w-14 rounded-sm"
          style={{ background: isDark ? '#FAFAFA' : '#1A1A1C' }}
        />
      </div>
    </div>
  );
}
