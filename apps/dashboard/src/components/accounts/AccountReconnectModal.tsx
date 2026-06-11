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
      title="Fix expiring tokens"
      description="Reconnect each account before the token window closes."
    >
      <div className="flex max-h-[60vh] flex-col gap-2 overflow-y-auto">
        {accounts.map((account) => (
          <div
            key={account.id}
            className="flex items-center gap-3 rounded-md border border-border bg-card px-3 py-2.5"
          >
            <div
              className="w-8 h-8 rounded-full shrink-0 flex items-center justify-center text-[0.75rem] font-semibold text-white"
              style={{
                background: `linear-gradient(135deg, ${account.groupColor}, color-mix(in srgb, ${account.groupColor} 60%, var(--color-ink)))`,
              }}
            >
              {(account.displayName[0] ?? '.').toUpperCase()}
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-[0.8125rem] font-medium text-foreground truncate">
                {account.handle}
              </div>
              <div className="text-[0.6875rem] text-muted-foreground tabular-nums">
                {formatFollowers(account.followers)} followers - {expiryLabel(account)}
              </div>
            </div>
            <Button
              type="button"
              onClick={() => {
                void reconnectAccount(account);
              }}
              size="sm"
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
