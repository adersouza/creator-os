import { Popover as RPopover } from 'radix-ui';
import React from 'react';
import { cn } from '@/lib/utils';

/**
 * Popover — thin Radix wrapper styled to match ContextMenu and DropdownMenu.
 * Radix handles focus management, dismiss (outside click + Esc), positioning
 * (flip + collision detection), and portaling. We add the glass shell.
 *
 * Use this for rich non-menu surfaces (filter panels, form snippets, draft
 * lists). For menu-shaped surfaces (action lists, pickers), use DropdownMenu
 * which provides arrow-key navigation and role=menu wiring out of the box.
 */

export const PopoverRoot = RPopover.Root;
export const PopoverTrigger = RPopover.Trigger;
export const PopoverAnchor = RPopover.Anchor;
export const PopoverClose = RPopover.Close;
export const PopoverPortal = RPopover.Portal;

export const PopoverContent = React.forwardRef<
  React.ElementRef<typeof RPopover.Content>,
  React.ComponentPropsWithoutRef<typeof RPopover.Content>
>(function PopoverContent({ className, sideOffset = 6, collisionPadding = 8, ...props }, ref) {
  return (
    <RPopover.Portal>
      <RPopover.Content
        ref={ref}
        sideOffset={sideOffset}
        collisionPadding={collisionPadding}
        className={cn(
          'composer-popover z-[95] min-w-[180px] sm:min-w-[200px] p-1 rounded-[10px]',
          'data-[state=open]:animate-ctx-in',
          'outline-none',
          className,
        )}
        {...props}
      />
    </RPopover.Portal>
  );
});
