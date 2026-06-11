import type React from 'react';
import { createPortal } from 'react-dom';
import { Ban, Check, Clock, Music2, Pause, ShieldCheck, SkipForward, Trash2, X } from 'lucide-react';
import { Button } from '@/components/ui/Button';

/* =========================================================================
   BULK ACTION BAR — bottom-pinned pill shown while posts are multi-selected.
   Extracted from src/pages/Calendar.tsx verbatim.
   ========================================================================= */
export function BulkActionBar({
  count,
  onPause,
  onReschedule,
  onDelete,
  onClear,
  campaignFactoryCount,
  onCampaignFactoryAudioAction,
}: {
  count: number;
  onPause: () => void;
  onReschedule: () => void;
  onDelete: () => void;
  onClear: () => void;
  campaignFactoryCount?: number | undefined;
  onCampaignFactoryAudioAction?: ((action: 'apply_primary_audio' | 'apply_first_recommendation' | 'selected' | 'attached' | 'verified' | 'skipped' | 'blocked') => void) | undefined;
}) {
  if (typeof document === 'undefined') return null;
  if (count <= 0) return null;

  return createPortal(
    <div
      style={{
        position: 'fixed',
        bottom: 24,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 7900,
      }}
      className="inline-flex items-center gap-1 rounded-full bg-foreground py-1.5 pl-4 pr-1.5 text-background shadow-[0_12px_36px_color-mix(in_srgb,var(--color-foreground)_24%,transparent),0_4px_12px_color-mix(in_srgb,var(--color-foreground)_12%,transparent)]"
    >
      <span className="mr-2 text-[0.78125rem] font-semibold tabular-nums">
        {count} selected
      </span>
      <BulkButton icon={<Pause data-icon="inline-start" />} label="Pause" onClick={onPause} />
      <BulkButton icon={<Clock data-icon="inline-start" />} label="Reschedule" onClick={onReschedule} />
      {campaignFactoryCount ? (
        <>
          <span className="mx-1 h-4 w-px bg-background/20" aria-hidden="true" />
          <BulkButton icon={<Music2 data-icon="inline-start" />} label="Use primary audio" onClick={() => onCampaignFactoryAudioAction?.('apply_primary_audio')} />
          <BulkButton icon={<Check data-icon="inline-start" />} label="Attached" onClick={() => onCampaignFactoryAudioAction?.('attached')} />
          <BulkButton icon={<ShieldCheck data-icon="inline-start" />} label="Verified" onClick={() => onCampaignFactoryAudioAction?.('verified')} />
          <BulkButton icon={<SkipForward data-icon="inline-start" />} label="Skipped" onClick={() => onCampaignFactoryAudioAction?.('skipped')} />
          <BulkButton icon={<Ban data-icon="inline-start" />} label="Blocked" onClick={() => onCampaignFactoryAudioAction?.('blocked')} />
        </>
      ) : null}
      <BulkButton
        icon={<Trash2 data-icon="inline-start" />}
        label="Delete"
        onClick={onDelete}
        danger
      />
      <Button
        type="button"
        aria-label="Clear selection"
        onClick={onClear}
        variant="ghost"
        size="icon"
        className="ml-1 h-11 w-11 rounded-full text-background hover:bg-background/10 hover:text-background sm:h-7 sm:w-7"
      >
        <X aria-hidden="true" />
      </Button>
    </div>,
    document.body,
  );
}

function BulkButton({ icon, label, onClick, danger }: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean | undefined;
}) {
  return (
    <Button
      type="button"
      onClick={onClick}
      aria-label={label}
      variant="ghost"
      size="sm"
      className={`h-11 rounded-full px-3 text-background hover:text-background sm:h-7 ${
        danger
          ? 'hover:bg-[color-mix(in_srgb,var(--color-oxblood)_80%,var(--color-background))]'
          : 'hover:bg-background/10'
      }`}
    >
      {icon}
      <span className="hidden sm:inline">{label}</span>
    </Button>
  );
}
