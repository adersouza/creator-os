import type React from 'react';
import {
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuRoot,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui/ContextMenu';

interface AccountRowContextMenuProps {
  children: React.ReactNode;
  pauseLabel: string;
  onOpen: () => void;
  onPause: () => void;
  onViewScheduler: () => void;
  onViewAnalytics: () => void;
  onMoveGroup: () => void;
  onSync: () => void;
  onHealthCheck: () => void;
  onReconnect: () => void;
  onRemove: () => void;
}

export function AccountRowContextMenu({
  children,
  pauseLabel,
  onOpen,
  onPause,
  onViewScheduler,
  onViewAnalytics,
  onMoveGroup,
  onSync,
  onHealthCheck,
  onReconnect,
  onRemove,
}: AccountRowContextMenuProps) {
  return (
    <ContextMenuRoot>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem onSelect={onOpen}>View</ContextMenuItem>
        <ContextMenuItem onSelect={onViewScheduler}>Open in Scheduler</ContextMenuItem>
        <ContextMenuItem onSelect={onViewAnalytics}>View analytics</ContextMenuItem>
        <ContextMenuItem onSelect={onPause}>{pauseLabel}</ContextMenuItem>
        <ContextMenuItem onSelect={onMoveGroup}>Move to group...</ContextMenuItem>
        <ContextMenuItem onSelect={onSync}>Sync now</ContextMenuItem>
        <ContextMenuItem onSelect={onHealthCheck}>Health check</ContextMenuItem>
        <ContextMenuItem onSelect={onReconnect}>Reconnect</ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem destructive onSelect={onRemove}>
          Remove
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenuRoot>
  );
}
