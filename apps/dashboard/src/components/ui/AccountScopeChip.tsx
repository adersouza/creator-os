import { forwardRef, type Ref } from 'react';
import { X } from 'lucide-react';

/**
 * AccountScopeChip — oxblood-10% pill used on page headers to indicate the
 * current account scope. Two modes:
 *   1. Scoped — pass `handle` + `color` + `onClear`; renders dot + @handle + ✕
 *   2. Fleet  — pass `count`; renders dot + "N account(s)"
 *
 * Previously copy-pasted word-for-word across Analytics.tsx, Attribution.tsx,
 * Calendar.tsx, CalendarHero.tsx, AnalyticsMobileLayout.tsx. One primitive.
 */

type BaseProps = {
  className?: string | undefined;
};

type ScopedProps = BaseProps & {
  mode?: 'scoped' | undefined;
  handle: string;
  color: string;
  onClear: () => void;
  count?: never | undefined;
};

type FleetProps = BaseProps & {
  mode?: 'fleet' | undefined;
  count: number;
  handle?: never | undefined;
  color?: never | undefined;
  onClear?: never | undefined;
};

type AccountScopeChipProps = ScopedProps | FleetProps;

export const AccountScopeChip = forwardRef<HTMLElement, AccountScopeChipProps>(
  function AccountScopeChip(props, ref) {
    const { className = '' } = props;
    const baseStyle = {
      backgroundColor: 'color-mix(in srgb, var(--color-oxblood) 10%, transparent)',
      color: 'var(--color-oxblood)',
    };

    if ('handle' in props && props.handle) {
      return (
        <button
          ref={ref as Ref<HTMLButtonElement>}
          type="button"
          onClick={props.onClear}
          className={`app-control-text inline-flex items-center gap-1.5 h-[22px] pl-2.5 pr-1.5 rounded-full transition-[filter,transform] hover:brightness-110 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-oxblood)] focus-visible:ring-offset-2 focus-visible:ring-offset-background ${className}`}
          style={baseStyle}
          aria-label={`Clear account scope (${props.handle})`}
        >
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{ backgroundColor: props.color }}
          />
          {props.handle}
          <X className="w-3 h-3 opacity-70" aria-hidden="true" />
        </button>
      );
    }

    // Fleet mode
    const count = (props as FleetProps).count;
    return (
      <span
        ref={ref as Ref<HTMLSpanElement>}
        className={`app-control-text inline-flex items-center gap-1.5 h-[22px] px-2.5 rounded-full ${className}`}
        style={baseStyle}
      >
        <span className="w-1.5 h-1.5 rounded-full bg-current opacity-70" />
        {count} account{count === 1 ? '' : 's'}
      </span>
    );
  },
);
