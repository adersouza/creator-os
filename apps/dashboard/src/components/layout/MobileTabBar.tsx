
import { useState, useCallback } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { Plus, MoreHorizontal } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/Button';
import { useNeedsAttention } from '@/hooks/useNeedsAttention';
import { Sheet } from '@/components/ui/Sheet';
import { useAccountScopeStore } from '@/stores/useAccountScopeStore';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import { isFleetResetMainNavPath, mainSidebarRoute } from '@/lib/scopedRoutes';
import { MOBILE_MORE_SECTIONS, PRIMARY_NAV } from '@/routes/routeRegistry';
import { ThemeToggle } from './ThemeToggle';

export { MOBILE_MORE_SECTIONS };

/**
 * Mobile bottom tab bar — 5 primary tabs + centered Compose + More overflow.
 * Layout: Home · Schedule · [+ Compose] · Accounts · Analytics · More
 * The "More" tab opens a bottom Sheet listing the remaining sidebar destinations
 * grouped by Insights / Publishing / Management — every URL the desktop sidebar
 * exposes is reachable on mobile.
 */
export function MobileTabBar() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const attention = useNeedsAttention();
  const attentionBadge = attention.totalCount;
  const [moreOpen, setMoreOpen] = useState(false);
  const scopedAccount = useAccountScopeStore((s) => s.scopedAccount);
  const clearScope = useAccountScopeStore((s) => s.clearScope);
  const clearGroupScope = useWorkspaceStore((s) => s.setSelectedGroupId);

  const isActive = (target: string) => {
    if (target === '/dashboard') return pathname === '/' || pathname === '/dashboard';
    return pathname.startsWith(target);
  };

  const routeFor = useCallback(
    (to: string) => (to === '/settings' ? to : mainSidebarRoute(to, { scopedAccount })),
    [scopedAccount],
  );

  const handleNav = useCallback(
    (to: string) => {
      if (isFleetResetMainNavPath(to)) {
        clearScope();
        clearGroupScope(null);
      }
      navigate(routeFor(to));
    },
    [clearGroupScope, clearScope, navigate, routeFor],
  );

  type Tab = { to: string; label: string; Icon: LucideIcon; badge?: number | undefined };
  const primaryByPath = new Map(PRIMARY_NAV.map((item) => [item.path, item]));
  const tabs: Tab[] = [
    {
      to: '/dashboard',
      label: 'Home',
      Icon: primaryByPath.get('/dashboard')?.icon ?? MoreHorizontal,
    },
    {
      to: '/calendar',
      label: 'Schedule',
      Icon: primaryByPath.get('/calendar')?.icon ?? MoreHorizontal,
    },
  ];
  const tabsRight: Tab[] = [
    {
      to: '/accounts',
      label: 'Accounts',
      Icon: primaryByPath.get('/accounts')?.icon ?? MoreHorizontal,
      badge: attentionBadge,
    },
    {
      to: '/analytics',
      label: 'Analytics',
      Icon: primaryByPath.get('/analytics')?.icon ?? MoreHorizontal,
    },
  ];

  const handleMoreNav = useCallback(
    (to: string) => {
      setMoreOpen(false);
      handleNav(to);
    },
    [handleNav],
  );

  const moreActive = MOBILE_MORE_SECTIONS.some((section) => section.items.some((item) => isActive(item.to)));

  return (
    <>
      <nav
        aria-label="Primary"
        className={cn(
          'mobile-tabbar md:hidden fixed bottom-0 inset-x-0 z-40 h-[80px]',
          'flex items-start justify-between px-3 pt-2.5',
        )}
        style={{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}
      >
        {tabs.map((tab) => (
          <MobileTab key={tab.to} {...tab} isActive={isActive(tab.to)} onNavigate={handleNav} />
        ))}

        {/* Compose CTA — center, elevated 48px circle, ink, lift shadow */}
        <Button
          asChild
          size="icon"
          className="-mt-[10px] size-12 rounded-full"
          aria-label="Compose new post"
        >
          <NavLink
            to="/composer"
            className={cn(
              'shadow-[0_2px_6px_rgba(10,10,11,0.18),0_8px_20px_rgba(10,10,11,0.1)]',
              'dark:shadow-[0_2px_8px_rgba(255,255,255,0.08)]',
            )}
          >
            <Plus aria-hidden="true" data-icon="inline-start" strokeWidth={2} />
          </NavLink>
        </Button>

        {tabsRight.map((tab) => (
          <MobileTab key={tab.to} {...tab} isActive={isActive(tab.to)} onNavigate={handleNav} />
        ))}

        <MoreTabButton
          isActive={moreActive && !moreOpen}
          isOpen={moreOpen}
          onClick={() => setMoreOpen(true)}
        />
      </nav>

      <Sheet
        open={moreOpen}
        onClose={() => setMoreOpen(false)}
        side="bottom"
        ariaLabel="More destinations"
        widthClass="w-full"
        hideCloseButton
        panelClassName="mobile-more-sheet"
      >
        <div className="px-4 pt-1 pb-6">
          <div className="mb-4 rounded-xl border border-border bg-card p-1">
            <ThemeToggle variant="row" />
          </div>
          {MOBILE_MORE_SECTIONS.map((section) => (
            <div key={section.title} className="mb-4 last:mb-0">
              <div className="text-[0.6875rem] font-semibold uppercase tracking-[0.14em] text-label-quaternary px-3 pb-2 pt-3">
                {section.title}
              </div>
              <ul className="flex flex-col">
                {section.items.map((item) => (
                  <li key={item.to}>
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => handleMoreNav(item.to)}
                      aria-current={isActive(item.to) ? 'page' : undefined}
                      className={cn(
                        'mobile-more-item flex items-center gap-3 w-full px-3 py-3 rounded-lg text-left',
                        'min-h-[48px] transition-colors',
                        'outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]',
                        isActive(item.to)
                          ? 'bg-muted text-foreground'
                          : 'text-foreground hover:bg-muted',
                      )}
                    >
                      <item.Icon
                        aria-hidden="true"
                        className={cn(
                          'w-[20px] h-[20px] shrink-0',
                          isActive(item.to) ? 'text-foreground' : 'text-label-tertiary',
                        )}
                        strokeWidth={1.5}
                      />
                      <span className="text-[0.9375rem] font-medium">{item.label}</span>
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </Sheet>
    </>
  );
}

function MoreTabButton({
  isActive,
  isOpen,
  onClick,
}: {
  isActive: boolean;
  isOpen: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onClick={onClick}
      aria-label="More destinations"
      aria-haspopup="dialog"
      aria-expanded={isOpen}
      className="mobile-tab-item flex min-h-[48px] w-12 min-w-0 flex-col items-center gap-0.5 px-0 pb-0.5 pt-1 outline-none focus-visible:rounded-md focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]"
    >
      <span className={cn('mobile-tab-icon-shell', (isActive || isOpen) && 'is-active')}>
        <MoreHorizontal
          aria-hidden="true"
          className={cn(
            'w-[21px] h-[21px] transition-colors',
            isActive || isOpen ? 'text-foreground' : 'text-label-tertiary',
          )}
          strokeWidth={1.5}
        />
      </span>
      <span
        className={cn(
          'text-[0.65625rem] leading-none transition-colors',
          isActive || isOpen ? 'text-foreground font-semibold' : 'text-label-tertiary font-medium',
        )}
      >
        More
      </span>
    </Button>
  );
}

function MobileTab({
  to,
  label,
  Icon,
  badge,
  isActive,
  onNavigate,
}: {
  to: string;
  label: string;
  Icon: LucideIcon;
  badge?: number | undefined;
  isActive: boolean;
  onNavigate: (to: string) => void;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onClick={() => onNavigate(to)}
      aria-current={isActive ? 'page' : undefined}
      aria-label={badge && badge > 0 ? `${label} (${badge} need attention)` : label}
      className="mobile-tab-item relative flex min-h-[48px] w-12 min-w-0 flex-col items-center gap-0.5 px-0 pb-0.5 pt-1 outline-none focus-visible:rounded-md focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]"
    >
      <span className={cn('mobile-tab-icon-shell', isActive && 'is-active')}>
        <Icon
          aria-hidden="true"
          className={cn(
            'w-[21px] h-[21px] transition-colors',
            isActive ? 'text-foreground' : 'text-label-tertiary',
          )}
          strokeWidth={1.5}
        />
        {badge !== undefined && badge > 0 && (
          <span
            aria-hidden="true"
            className={cn(
              'absolute -top-1 -right-2 min-w-[16px] h-[16px] px-1',
              'inline-flex items-center justify-center rounded-full',
              'text-[0.5625rem] font-semibold tabular-nums text-white',
              'shadow-[0_1px_2px_rgba(10,10,11,0.3)]',
            )}
            style={{ backgroundColor: 'var(--color-oxblood)' }}
          >
            {badge > 99 ? '99+' : badge}
          </span>
        )}
      </span>
      <span
        className={cn(
          'text-[0.65625rem] leading-none transition-colors',
          isActive ? 'text-foreground font-semibold' : 'text-label-tertiary font-medium',
        )}
      >
        {label}
      </span>
    </Button>
  );
}
