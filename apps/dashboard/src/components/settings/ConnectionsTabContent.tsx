import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AtSign,
  Camera,
  CheckCircle2,
  CreditCard,
  Hash,
  Loader2,
  Sparkles,
} from 'lucide-react';
import { appToast } from '@/lib/toast';
import { supabase } from '@/services/supabase';
import { Badge } from '@/components/ui/Badge';
import { BrandLogo, type BrandLogoName } from '@/components/ui/BrandLogo';
import { Button } from '@/components/ui/Button';
import { NovaCard, NovaEmpty } from '@/components/ui/NovaPrimitives';
import { Skeleton } from '@/components/ui/Skeleton';
import { useConnectedAccounts } from '@/hooks/useConnectedAccounts';
import { useFleetAccounts, type FleetAccount } from '@/hooks/useFleetAccounts';
import { useTrialStatus } from '@/hooks/useTrialStatus';
import { useUserTier } from '@/hooks/useUserTier';
import { labelFor } from '@/lib/socialPlatform';

import { VoiceProfileEditor } from './VoiceProfileEditor';
import { SectionHeader } from './shared';

/* ============================================================================
   Connections tab group — third-party integrations (OAuth + billing) and
   per-account AI voice profiles. Extracted verbatim from Settings.tsx; the
   only change is the two sibling tabs now live in one file because they
   share no state and router between them is pure navigation.
   ========================================================================= */

interface Connection {
  id: string;
  name: string;
  sub: string;
  connected: boolean;
  disabled?: boolean | undefined;
  Icon: typeof Camera;
}

const PROVIDERS = [
  { id: 'threads', name: 'Threads', logo: 'threads', live: true },
  { id: 'instagram', name: 'Instagram', logo: 'instagram', live: true },
  { id: 'meta', name: 'Meta', logo: 'meta', live: true },
  { id: 'x', name: 'X', glyph: 'X', live: false },
  { id: 'linkedin', name: 'LinkedIn', glyph: 'IN', live: false },
  { id: 'bluesky', name: 'Bluesky', glyph: 'BS', live: false },
] as const;

export function ConnectionsTabContent() {
  const navigate = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const { accounts, isLoading } = useConnectedAccounts();
  const { tier } = useUserTier();
  const { isTrialing, daysRemaining } = useTrialStatus();
  const threadsCount = accounts.filter((account) => account.platform === 'threads').length;
  const instagramCount = accounts.filter((account) => account.platform === 'instagram').length;
  const stripeConnected = tier !== 'free' || isTrialing;
  const connections: Connection[] = [
    {
      id: 'ig',
      name: 'Instagram',
      sub: instagramCount > 0
        ? `Graph API · ${instagramCount} account${instagramCount === 1 ? '' : 's'}`
        : 'Graph API · Not connected',
      connected: instagramCount > 0,
      Icon: Camera,
    },
    {
      id: 'threads',
      name: 'Threads',
      sub: threadsCount > 0
        ? `Meta OAuth · ${threadsCount} account${threadsCount === 1 ? '' : 's'}`
        : 'Meta OAuth · Not connected',
      connected: threadsCount > 0,
      Icon: AtSign,
    },
    {
      id: 'stripe',
      name: 'Stripe',
      sub: stripeConnected
        ? isTrialing
          ? `Trial active · ${daysRemaining} day${daysRemaining === 1 ? '' : 's'} left`
          : `Plan active · ${tier}`
        : 'Billing available',
      connected: stripeConnected,
      Icon: CreditCard,
    },
    {
      id: 'x',
      name: 'X (Twitter)',
      sub: 'Not connected',
      connected: false,
      disabled: true,
      Icon: Hash,
    },
  ];

  const handleAction = async (conn: Connection) => {
    if (busy) return;
    try {
      if (conn.id === 'ig' || conn.id === 'threads') {
        if (conn.connected) {
          navigate('/accounts');
          return;
        }
        setBusy(conn.id);
        const { initiateLogin, initiateInstagramLogin } = await import('@/services/api/accounts');
        const { authUrl } = conn.id === 'threads'
          ? await initiateLogin()
          : await initiateInstagramLogin();
        window.location.href = authUrl;
      } else if (conn.id === 'stripe') {
        navigate('/billing');
      } else if (conn.id === 'x') {
        appToast.info('X support is on the roadmap — not available yet.');
      }
    } catch (err) {
      appToast.error(`Could not open ${conn.name}`, {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <SectionHeader
        title="Connections"
        description="Third-party integrations for publishing, analytics, and billing."
      />

      <NovaCard
        eyebrow="Provider row"
        title="Publishing network surface"
        action={<Badge tone="secondary">Roadmap visible</Badge>}
        contentClassName="p-0"
      >
        <div className="grid grid-cols-2 divide-x divide-y divide-border sm:grid-cols-3 lg:grid-cols-6">
          {PROVIDERS.map((provider) => {
            const connected =
              (provider.id === 'threads' && threadsCount > 0) ||
              (provider.id === 'instagram' && instagramCount > 0);
            return (
              <div
                key={provider.id}
                className="flex min-h-[104px] flex-col justify-between gap-3 p-3"
              >
                <div className="flex items-center justify-between gap-2">
                  <span
                    className={`inline-flex h-8 w-8 items-center justify-center rounded-md border font-mono text-[0.6875rem] font-bold ${
                      provider.live
                        ? 'border-[color-mix(in_srgb,var(--color-oxblood)_28%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-oxblood)_9%,transparent)] text-[color:var(--color-oxblood)]'
                        : 'border-border bg-muted text-muted-foreground'
                    }`}
                  >
                    {'logo' in provider ? (
                      <BrandLogo
                        name={provider.logo as BrandLogoName}
                        size="sm"
                        monochrome
                      />
                    ) : (
                      provider.glyph
                    )}
                  </span>
                  <Badge tone={connected ? 'oxblood' : 'secondary'}>
                    {connected ? 'linked' : provider.live ? 'live' : 'soon'}
                  </Badge>
                </div>
                <div>
                  <div className="text-[0.8125rem] font-semibold text-foreground">{provider.name}</div>
                  <div className="mt-0.5 text-[0.6875rem] font-medium text-muted-foreground">
                    {connected ? 'OAuth active' : provider.live ? 'Connectable' : 'Coming soon'}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </NovaCard>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {connections.map((c) => {
          const unsupported = c.disabled === true;
          return (
            <NovaCard key={c.id} variant="compact" contentClassName="flex items-start gap-3">
              <div
                className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 ${
                  c.connected
                    ? 'bg-foreground text-background'
                    : 'bg-muted text-muted-foreground border border-border'
                }`}
              >
                {c.id === 'ig' ? (
                  <BrandLogo name="instagram" size="sm" monochrome />
                ) : c.id === 'threads' ? (
                  <BrandLogo name="threads" size="sm" monochrome />
                ) : c.id === 'stripe' ? (
                  <BrandLogo name="stripe" size="sm" monochrome />
                ) : (
                  <c.Icon className="w-4 h-4" />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-[0.84375rem] font-medium text-foreground">{c.name}</span>
                  {c.connected ? (
                    <Badge tone="oxblood">
                      <CheckCircle2 data-icon="inline-start" aria-hidden="true" />
                      Linked
                    </Badge>
                  ) : unsupported ? (
                    <Badge tone="secondary">Coming soon</Badge>
                  ) : (
                    <Badge tone="outline">Off</Badge>
                  )}
                </div>
                <div className="text-[0.71875rem] text-muted-foreground mt-0.5">{c.sub}</div>
                <div className="mt-3">
                  <Button
                    variant={c.connected ? 'outline' : 'default'}
                    className="h-8 text-[0.75rem]"
                    onClick={() => void handleAction(c)}
                    disabled={unsupported || busy === c.id || isLoading}
                  >
                    {busy === c.id
                      ? 'Opening…'
                      : unsupported
                      ? 'Unavailable'
                      : c.connected
                      ? 'Configure'
                      : 'Connect'}
                  </Button>
                </div>
              </div>
            </NovaCard>
          );
        })}
      </div>
    </div>
  );
}

/* ============================================================================
   Voice profiles — per-account `ai_config`. The Composer's Match-Voice
   button and every AI generate call reads this server-side via the
   `/api/ai?action=generate` prompt-builder; here's the UI that actually
   populates it.
   ========================================================================= */

export function VoiceProfilesTabContent() {
  const { accounts, isLoading } = useFleetAccounts();
  const [editing, setEditing] = useState<FleetAccount | null>(null);
  const [configuredIds, setConfiguredIds] = useState<Set<string>>(new Set());
  const [checking, setChecking] = useState(true);

  // Lightweight check: for each account, hit ai_config and note whether it's
  // been set up. Runs once per account list; re-runs after a save via the
  // editor's `onSaved` callback.
  const refreshStatuses = useCallback(async () => {
    if (accounts.length === 0) {
      setConfiguredIds(new Set());
      setChecking(false);
      return;
    }
    setChecking(true);
    const threadsIds = accounts.filter((a) => a.platform === 'threads').map((a) => a.id);
    const igIds = accounts.filter((a) => a.platform === 'instagram').map((a) => a.id);

    const [threadsRes, igRes] = await Promise.all([
      threadsIds.length
        ? supabase.from('accounts').select('id, ai_config').in('id', threadsIds)
        : Promise.resolve({ data: [] as { id: string; ai_config: unknown }[], error: null }),
      igIds.length
        ? supabase.from('instagram_accounts').select('id, ai_config').in('id', igIds)
        : Promise.resolve({ data: [] as { id: string; ai_config: unknown }[], error: null }),
    ]);

    const next = new Set<string>();
    const check = (rows: { id: string; ai_config: unknown }[] | null) => {
      (rows ?? []).forEach((r) => {
        if (r.ai_config && typeof r.ai_config === 'object' && Object.keys(r.ai_config).length > 0) {
          next.add(r.id);
        }
      });
    };
    check(threadsRes.data);
    check(igRes.data);
    setConfiguredIds(next);
    setChecking(false);
  }, [accounts]);

  useEffect(() => {
    void refreshStatuses();
  }, [refreshStatuses]);

  return (
    <div className="flex flex-col gap-6">
      <SectionHeader
        title="Voice profiles"
        description="Teach Juno33 how each account writes. The Composer's AI tools and every autopilot generate call read these per-account rules when producing copy."
      />

      <NovaCard variant="panel" contentClassName="flex items-start gap-3">
        <div className="w-8 h-8 rounded-md flex items-center justify-center shrink-0 bg-muted text-muted-foreground border border-border">
          <Sparkles className="w-4 h-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[0.78125rem] font-medium text-foreground">
            Start with auto-extract, then refine
          </div>
          <div className="text-[0.71875rem] text-muted-foreground mt-0.5 leading-relaxed">
            Paste 3–20 of an account's best captions inside the editor. Juno33
            analyses length, emoji cadence, tone words, and personality, then fills in
            the fields so you can tweak. The backend injects it into every prompt —
            no extra step at Compose time.
          </div>
        </div>
      </NovaCard>

      {isLoading || checking ? (
        <NovaCard>
          <div className="flex items-center gap-3 text-muted-foreground">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span className="text-[0.8125rem]">Loading accounts…</span>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </div>
        </NovaCard>
      ) : accounts.length === 0 ? (
        <NovaEmpty
          icon={<AtSign data-icon aria-hidden="true" />}
          title="No connected accounts yet"
          description="Connect Threads or Instagram accounts to set up per-account voice profiles."
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {accounts.map((acc) => {
            const configured = configuredIds.has(acc.id);
            return (
              <NovaCard key={acc.id} variant="compact" contentClassName="flex items-start gap-3">
                <div
                  className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0 bg-muted text-muted-foreground border border-border"
                  style={{ color: acc.groupColor }}
                >
                  <AtSign className="w-4 h-4" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[0.84375rem] font-medium text-foreground truncate">
                      {acc.handle}
                    </span>
                    <Badge tone="secondary">{labelFor(acc.platform)}</Badge>
                    {configured ? (
                      <Badge tone="oxblood">
                        <CheckCircle2 data-icon="inline-start" aria-hidden="true" />
                        Voice set
                      </Badge>
                    ) : (
                      <Badge tone="outline">Not configured</Badge>
                    )}
                  </div>
                  <div className="text-[0.71875rem] text-muted-foreground mt-0.5 truncate">
                    {acc.groupName} · {acc.followers.toLocaleString()} followers
                  </div>
                  <div className="mt-3">
                    <Button
                      variant={configured ? 'outline' : 'default'}
                      className="h-8 text-[0.75rem]"
                      onClick={() => setEditing(acc)}
                    >
                      {configured ? 'Edit voice' : 'Set up voice'}
                    </Button>
                  </div>
                </div>
              </NovaCard>
            );
          })}
        </div>
      )}

      {editing && (
        <VoiceProfileEditor
          open={!!editing}
          onClose={() => setEditing(null)}
          accountId={editing.id}
          platform={editing.platform}
          handle={editing.handle}
          onSaved={() => {
            void refreshStatuses();
          }}
        />
      )}
    </div>
  );
}
