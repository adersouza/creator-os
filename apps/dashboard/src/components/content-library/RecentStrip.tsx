import type React from "react";
import { Badge } from "@/components/ui/Badge";
import { NovaCard } from "@/components/ui/NovaPrimitives";

export function RecentStrip<T extends { id: string }>({
  items,
  renderItem,
  label = "Recently used",
}: {
  items: T[];
  renderItem: (item: T) => React.ReactNode;
  label?: string;
}) {
  if (items.length === 0) return null;

  return (
    <NovaCard
      aria-labelledby="recent-eyebrow"
      className="mb-6"
      contentClassName="p-3"
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <span
          id="recent-eyebrow"
          className="text-sm font-medium text-muted-foreground"
        >
          {label}
        </span>
        <Badge tone="outline" className="tabular-nums">
          {items.length} shown
        </Badge>
      </div>
      <div className="flex items-stretch gap-3 overflow-x-auto pb-1 scrollbar-hide">
        {items.map((item) => renderItem(item))}
      </div>
    </NovaCard>
  );
}
