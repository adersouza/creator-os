import { Badge } from '@/components/ui/Badge';
import { BrandLogo } from '@/components/ui/BrandLogo';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { NovaEmpty } from '@/components/ui/NovaPrimitives';
import type { FleetAccount } from '@/hooks/useFleetAccounts';
import { initiateInstagramLogin, initiateLogin } from '@/services/api/accounts';
import { appToast } from '@/lib/toast';
import { formatFollowers } from './shared';

interface AccountReconnectModalProps {
  open: boolean;
  accounts: FleetAccount[];
  onClose: () => void;
}

export function AccountReconnectModal({ open, accounts, onClose }: AccountReconnectModalProps) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Reconnect accounts"
      description="Refresh platform access before publishing and sync actions fail."
    >
      <div className="flex max-h-[60vh] flex-col gap-2 overflow-y-auto">
        {accounts.map((account) => (
          <div
            key={account.id}
            className="flex items-center gap-3 rounded-lg border border-border bg-muted/45 px-3 py-3"
          >
            <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-border bg-card text-muted-foreground">
              <BrandLogo
                name={account.platform === 'instagram' ? 'instagram' : 'threads'}
                size="sm"
                monochrome
              />
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[0.8125rem] font-medium text-foreground truncate">
                {account.handle}
              </div>
              <div className="mt-1 flex min-w-0 flex-wrap items-center gap-1.5 text-[0.6875rem] text-muted-foreground tabular-nums">
                <span>{formatFollowers(account.followers)} followers</span>
                <Badge
                  tone={account.needsReauth || account.tokenDaysLeft !== null && account.tokenDaysLeft <= 0 ? 'danger' : 'outline'}
                  className="text-[0.65625rem]"
                >
                  {expiryLabel(account)}
                </Badge>
              </div>
            </div>
            <Button
              type="button"
              onClick={() => {
                void reconnectAccount(account);
              }}
              size="sm"
              haptic="warning"
            >
              Reconnect
            </Button>
          </div>
        ))}
        {accounts.length === 0 && (
          <NovaEmpty
            title="No expiring tokens"
            description="No selected accounts have expiring tokens."
          />
        )}
      </div>
    </Modal>
  );
}

async function reconnectAccount(account: FleetAccount) {
  try {
    localStorage.setItem('juno33-oauth-source', 'accounts');
    sessionStorage.setItem(
      'juno33:oauth-reconnect',
      JSON.stringify({
        accountId: account.id,
        platform: account.platform,
        returnTo: `/accounts?reconnect=${encodeURIComponent(account.id)}`,
      }),
    );
    const { authUrl } =
      account.platform === 'instagram'
        ? await initiateInstagramLogin({ forceReauth: true })
        : await initiateLogin();
    window.location.assign(authUrl);
  } catch (error) {
    appToast.error('Could not start reconnect', {
      description: error instanceof Error ? error.message : undefined,
    });
  }
}

function expiryLabel(account: FleetAccount): string {
  if (account.needsReauth) return 'needs reauth now';
  if (account.tokenDaysLeft === null) return 'token status unknown';
  if (account.tokenDaysLeft < 0) return 'expired';
  if (account.tokenDaysLeft === 0) return 'expires today';
  return `expires in ${account.tokenDaysLeft}d`;
}
