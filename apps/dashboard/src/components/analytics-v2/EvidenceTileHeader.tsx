import type { ReactNode } from 'react';
import { Database, Filter, RefreshCw } from 'lucide-react';
import { useAccountScopeStore } from '@/stores/useAccountScopeStore';

interface Props {
  /** Legacy inventory index. Accepted for compatibility, never shown in UI. */
  index?: number | undefined;
  /** Product category label. Internal labels like "Analytics" are suppressed. */
  eyebrow?: string | undefined;
  title: string;
  /** Tertiary line under the title. */
  hint?: string | undefined;
  /** Override for the provenance/freshness line. Use null to suppress. */
  dataQuality?: string | null | undefined;
  /** Right-side action slot (typically <InvestigateButton/> or chip group). */
  action?: ReactNode | undefined;
}

/**
 * Standard header for analytics-v2 evidence tiles. Three regions:
 *   - Left: optional product category + title + optional hint
 *   - Right: action slot (Investigate button, segmented control, etc.)
 *
 * The old audit inventory labels ("Analytics · §17") were intentionally
 * removed from the visible UI. Widget headers should read like product
 * surfaces, not implementation checklists.
 */
export function EvidenceTileHeader({ eyebrow, title, hint, dataQuality, action }: Props) {
  const cleanEyebrow = sanitizeEyebrow(eyebrow);
  const scopedAccount = useAccountScopeStore((state) => state.scopedAccount);
  const qualityText =
    dataQuality === null
      ? null
      : dataQuality ??
        `${scopedAccount ? `@${scopedAccount.handle}` : 'Selected filter'} · synced account data`;
  return (
    <header className="flex min-w-0 flex-wrap items-start justify-between gap-3 px-6 pt-5 pb-3">
      <div className="flex min-w-0 flex-1 basis-64 flex-col gap-1">
        {cleanEyebrow ? (
          <span className="eyebrow">{cleanEyebrow}</span>
        ) : null}
        <h3 className="text-[1rem] font-semibold leading-snug text-foreground">{title}</h3>
        {hint ? <p className="text-[0.75rem] leading-snug text-muted-foreground">{hint}</p> : null}
        {qualityText ? (
          <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[0.6875rem] leading-snug text-muted-foreground">
            <span className="inline-flex min-w-0 items-center gap-1">
              <Filter className="h-3 w-3 shrink-0" aria-hidden="true" />
              <span className="truncate">{qualityText}</span>
            </span>
            <span className="inline-flex items-center gap-1">
              <Database className="h-3 w-3 shrink-0" aria-hidden="true" />
              <span>No synthetic samples</span>
            </span>
            <span className="inline-flex items-center gap-1">
              <RefreshCw className="h-3 w-3 shrink-0" aria-hidden="true" />
              <span>Refreshes with sync</span>
            </span>
          </div>
        ) : null}
      </div>
      {action ? <div className="flex max-w-full min-w-0 flex-wrap items-center justify-start gap-2 sm:justify-end">{action}</div> : null}
    </header>
  );
}

function sanitizeEyebrow(value?: string): string | null {
  if (!value) return null;
  const trimmed = value
    .replace(/(?:^|\s)§\s*\d+\b/g, '')
    .replace(/\s*·\s*$/g, '')
    .trim();
  if (!trimmed) return null;
  if (/^(analytics|evidence|upcoming)$/i.test(trimmed)) return null;
  return trimmed;
}
