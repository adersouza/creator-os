import React from 'react';
import {
	Card as ShadCard,
	CardContent as ShadCardContent,
	CardDescription as ShadCardDescription,
	CardFooter as ShadCardFooter,
	CardHeader as ShadCardHeader,
	CardTitle as ShadCardTitle,
} from "@/components/shadcn/card";
import { cn } from '@/lib/utils';

export type CardMaterial = 'ultra-thin' | 'thin' | 'regular' | 'thick' | 'dense';
export type CardSize = 'default' | 'sm';

const MATERIAL_TIER_CLASS: Record<CardMaterial, string> = {
  'ultra-thin': 'bg-card/80',
  thin: 'bg-card',
  regular: 'bg-card',
  thick: 'bg-card shadow-sm',
  dense: 'bg-card',
};

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  /**
   * Compatibility material prop. These now map to Dashboard V2 elite j33 tiers
   * instead of legacy Liquid Glass classes.
   */
  material?: CardMaterial | undefined;
  size?: CardSize | undefined;
}

export const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, material = 'regular', size = 'default', ...props }, ref) => (
    <ShadCard
      ref={ref}
      data-size={size}
      className={cn(
        MATERIAL_TIER_CLASS[material],
        'relative overflow-hidden rounded-xl border border-border text-card-foreground shadow-sm',
        size === 'sm' && 'text-sm',
        className,
      )}
      {...props}
    />
  )
);
Card.displayName = "Card";

export const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <ShadCardHeader ref={ref} className={cn("flex-row items-start justify-between gap-3 p-5", className)} {...props} />
  )
);
CardHeader.displayName = "CardHeader";

export const CardTitle = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <ShadCardTitle ref={ref} className={cn("app-card-title text-foreground", className)} {...props} />
  )
);
CardTitle.displayName = "CardTitle";

export const CardDescription = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLParagraphElement>>(
  ({ className, ...props }, ref) => (
    <ShadCardDescription ref={ref} className={cn("app-caption text-muted-foreground", className)} {...props} />
  )
);
CardDescription.displayName = "CardDescription";

export const CardAction = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("ml-auto flex shrink-0 items-center gap-2", className)} {...props} />
  )
);
CardAction.displayName = "CardAction";

export const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <ShadCardContent ref={ref} className={cn("p-5 pt-0", className)} {...props} />
  )
);
CardContent.displayName = "CardContent";

export const CardFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <ShadCardFooter ref={ref} className={cn("gap-2 border-t border-border bg-muted/35 p-5", className)} {...props} />
  )
);
CardFooter.displayName = "CardFooter";
