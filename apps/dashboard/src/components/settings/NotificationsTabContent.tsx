import { useEffect, useState } from 'react';
import { AlertCircle } from 'lucide-react';
import { appToast } from '@/lib/toast';
import { supabase } from '@/services/supabase';
import { getUserSetting, upsertUserSetting } from '@/services/userSettingsService';
import { useAuthUser } from '@/hooks/useAuthUser';
import { PublishingReadinessPanel } from '@/components/publishing/PublishingReadinessPanel';
import { PublishingStartCard } from '@/components/publishing/PublishingStartCard';
import { PhoneSetupChecklist } from '@/components/publishing/PhoneSetupChecklist';
import { useConnectedAccounts } from '@/hooks/useConnectedAccounts';
import { apiUrl } from '@/lib/apiUrl';
import { buildPublishingReadinessIssues } from '@/lib/publishingReadiness';
import { detectPwaInstallState } from '@/lib/pwaSetup';
import { trackClientEvent } from '@/services/clientTelemetry';
import type { PwaInstallState } from '@/types/publishingReadiness';

import { Panel, SectionHeader, Toggle } from './shared';

const EMAIL_DIGEST_KEY = 'notification_email_digest';
const EMAIL_PUBLISH_FAIL_KEY = 'notification_email_publish_fail';
const EMAIL_TOKEN_EXPIRY_KEY = 'notification_email_token_expiry';
const MARKETING_OPT_IN_KEY = 'marketing_opt_in';

/* ============================================================================
   Notifications tab — email digest preferences + browser push subscription.
   Hydrates from existing user_settings keys, then persists every toggle change
   back via upsert. Push state is checked live against the active
   ServiceWorker subscription so UI and reality stay in sync.
   ========================================================================= */

export function NotificationsTabContent() {
  const _authUser = useAuthUser();
  const { accounts } = useConnectedAccounts();
  const [digest, setDigest] = useState(true);
  const [publishFail, setPublishFail] = useState(true);
  const [tokenExpiry, setTokenExpiry] = useState(true);
  const [marketingOptIn, setMarketingOptIn] = useState(false);
  const [browserPush, setBrowserPush] = useState(false);
  const [pushBusy, setPushBusy] = useState(false);
  const [prefsHydrated, setPrefsHydrated] = useState(false);
  const [pwaState, setPwaState] = useState<PwaInstallState>('desktop');

  useEffect(() => {
    setPwaState(detectPwaInstallState());
  }, []);

  // Hydrate saved prefs from Supabase + existing push subscription state
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user || cancelled) {
        setPrefsHydrated(true);
        return;
      }
      const [savedDigest, savedPublishFail, savedTokenExpiry, marketing] = await Promise.all([
        getUserSetting(user.id, EMAIL_DIGEST_KEY).catch(() => null),
        getUserSetting(user.id, EMAIL_PUBLISH_FAIL_KEY).catch(() => null),
        getUserSetting(user.id, EMAIL_TOKEN_EXPIRY_KEY).catch(() => null),
        getUserSetting(user.id, MARKETING_OPT_IN_KEY).catch(() => null),
      ]);
      if (cancelled) return;
      setDigest(savedDigest !== false);
      setPublishFail(savedPublishFail !== false);
      setTokenExpiry(savedTokenExpiry !== false);
      setMarketingOptIn(marketing === true);
      // Live check: is there an active push subscription right now?
      if ('serviceWorker' in navigator && 'PushManager' in window) {
        try {
          const reg = await navigator.serviceWorker.ready;
          const sub = await reg.pushManager.getSubscription();
          if (!cancelled) setBrowserPush(!!sub);
        } catch {
          /* ignore */
        }
      }
      setPrefsHydrated(true);
    })();
    return () => { cancelled = true; };
  }, []);

  // Persist email prefs on any change (after hydration)
  useEffect(() => {
    if (!prefsHydrated) return;
    (async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return;
      await Promise.all([
        upsertUserSetting(user.id, EMAIL_DIGEST_KEY, digest),
        upsertUserSetting(user.id, EMAIL_PUBLISH_FAIL_KEY, publishFail),
        upsertUserSetting(user.id, EMAIL_TOKEN_EXPIRY_KEY, tokenExpiry),
      ]);
    })();
  }, [digest, publishFail, tokenExpiry, prefsHydrated]);

  // Marketing opt-in shares the same user_settings KV path as other lightweight
  // notification preferences. GDPR default: opt-out, explicit opt-in.
  useEffect(() => {
    if (!prefsHydrated) return;
    (async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return;
      try {
        await upsertUserSetting(user.id, MARKETING_OPT_IN_KEY, marketingOptIn);
      } catch {
        /* silent — non-critical pref */
      }
    })();
  }, [marketingOptIn, prefsHydrated]);

  const handleBrowserPushToggle = async (next: boolean) => {
    if (pushBusy) return;
    setPushBusy(true);
    try {
      const { subscribeToPush, unsubscribeFromPush, isPushSupported } = await import(
        '@/services/pushSubscriptionService'
      );
      if (!isPushSupported()) {
        appToast.error('Browser push not supported on this device.');
        return;
      }
      if (next) {
        const ok = await subscribeToPush();
        if (!ok) {
          appToast.error('Push subscription failed', {
            description: 'Check that notifications are allowed for this site.',
          });
          return;
        }
        setBrowserPush(true);
        appToast.success('Desktop push enabled');
      } else {
        await unsubscribeFromPush();
        setBrowserPush(false);
        appToast.success('Desktop push disabled');
      }
    } finally {
      setPushBusy(false);
    }
  };

  const sendTestPush = async () => {
    setPushBusy(true);
    try {
      const {
        data: { session },
      } = await supabase.auth.getSession();
      if (!session?.access_token) throw new Error('Not authenticated');
      const response = await fetch(apiUrl('/api/notifications?action=test-push'), {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${session.access_token}`,
          'Content-Type': 'application/json',
        },
      });
      if (!response.ok) throw new Error('Test notification failed');
      appToast.success('Test notification sent');
      trackClientEvent('pwa_setup_step_completed', {
        step: 'settings_test_push',
      });
    } catch (error) {
      appToast.error('Could not send test notification', {
        description: error instanceof Error ? error.message : undefined,
      });
    } finally {
      setPushBusy(false);
    }
  };

  const readinessIssues = buildPublishingReadinessIssues({
    hasInstagramAccount: accounts.some((account) => account.platform === 'instagram'),
    pushState: browserPush ? 'subscribed' : 'not-subscribed',
    pwaState,
    instagramReady: false,
  }).map((issue) => {
    if (issue.id === 'notify-push') return { ...issue, action: () => void handleBrowserPushToggle(true) };
    if (issue.id === 'pwa-install' || issue.id === 'instagram-app') return { ...issue, action: () => window.location.assign('/setup/publishing') };
    if (issue.id === 'instagram-account') return { ...issue, action: () => window.location.assign('/welcome') };
    return issue;
  });

  return (
    <div className="flex flex-col gap-6">
      <SectionHeader
        title="Notifications"
        description="Choose what's worth pulling you back to Juno33 during the day — and what can wait for the weekly digest."
      />

      <PublishingStartCard surface="settings_notifications" />

      <PublishingReadinessPanel
        issues={readinessIssues}
        compact
        onIssueAction={(issue) =>
          trackClientEvent('account_readiness_action_clicked', {
            issue_id: issue.id,
            state: issue.state,
            surface: 'settings_notifications',
          })
        }
      />

      <PhoneSetupChecklist
        pwaState={pwaState}
        pushState={browserPush ? 'subscribed' : 'not-subscribed'}
        busy={pushBusy}
        compact
        onEnablePush={() => void handleBrowserPushToggle(true)}
        onSendTestPush={() => void sendTestPush()}
        onConfirmInstagram={() => {
          trackClientEvent('pwa_setup_step_completed', {
            step: 'settings_instagram_confirmed',
          });
          window.location.assign('/setup/publishing');
        }}
      />

      <Panel>
        <div className="text-[0.6875rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground mb-1">
          Email
        </div>
        <Toggle
          label="Weekly digest"
          sub="A Monday summary of your fleet: EQS trend, top posts, flagged accounts, AI insights."
          checked={digest}
          onCheckedChange={setDigest}
        />
        <Toggle
          label="Publish failures"
          sub="Email me when a scheduled post fails to publish after retries."
          checked={publishFail}
          onCheckedChange={setPublishFail}
        />
        <Toggle
          label="Token expiry"
          sub="48-hour warning before a connected account's OAuth token expires."
          checked={tokenExpiry}
          onCheckedChange={setTokenExpiry}
        />
        <Toggle
          label="Product updates & tips"
          sub="Occasional emails about new Juno33 features, playbooks, and early-access programs. Off by default."
          checked={marketingOptIn}
          onCheckedChange={setMarketingOptIn}
        />
      </Panel>

      <Panel>
        <div className="text-[0.6875rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground mb-1">
          Browser
        </div>
        <Toggle
          label="Desktop push"
          sub="Instant push for critical events (publish failures, token revoked)."
          checked={browserPush}
          onCheckedChange={handleBrowserPushToggle}
        />
        {browserPush && (
          <div
            className="mt-2 p-3 rounded-md text-[0.71875rem] flex items-start gap-2"
            style={{
              backgroundColor: 'color-mix(in srgb, var(--color-oxblood) 8%, transparent)',
              color: 'var(--color-oxblood)',
            }}
          >
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-px" />
            <span>Your browser will prompt for permission the first time we send a push.</span>
          </div>
        )}
      </Panel>
    </div>
  );
}
