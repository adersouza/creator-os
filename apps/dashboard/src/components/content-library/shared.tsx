import type React from "react";
import { Badge } from "@/components/ui/Badge";
import { BrandLogo } from "@/components/ui/BrandLogo";
import { NovaEmpty, NovaMiniStat } from "@/components/ui/NovaPrimitives";
import { StatusPill } from "@/components/ui/StatusPill";
import { cn } from "@/lib/utils";
import type { PlatformKind } from "./types";

export function PlatformIcon({
  platform,
  className,
}: {
  platform: PlatformKind;
  className?: string | undefined;
}) {
  return (
    <BrandLogo
      name={platform}
      size="xs"
      monochrome
      className={cn("size-3", className)}
    />
  );
}

export function TypePill({
  label,
  icon: Icon,
  tone = "ink",
}: {
  label: string;
  icon?: React.ComponentType<{ className?: string | undefined }> | undefined;
  tone?: "ink" | "oxblood" | "gold" | "harbor" | undefined;
}) {
  const pillTone =
    tone === "oxblood" ? "oxblood" : tone === "gold" ? "warn" : "info";
  const style =
    tone === "harbor"
      ? {
          color: "var(--color-harbor)",
          backgroundColor: "color-mix(in_srgb,var(--color-muted-foreground)_12%,transparent)",
        }
      : undefined;
  return (
    <StatusPill
      tone={pillTone}
      size="xs"
      icon={Icon ? <Icon /> : null}
      className="!rounded !px-1.5"
      style={style}
    >
      {label}
    </StatusPill>
  );
}

export function TagChip({ children }: { children: React.ReactNode }) {
  return (
    <Badge tone="outline" className="normal-case tracking-normal">
      {children}
    </Badge>
  );
}

export function MetaDot() {
  return <span className="text-muted-foreground">·</span>;
}

export function StatCell({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string | undefined;
}) {
  return (
    <NovaMiniStat
      label={label}
      value={value}
      description={detail}
    />
  );
}

export function InlineEmpty({
  title,
  detail,
}: {
  title: string;
  detail: string;
}) {
  return (
    <NovaEmpty
      title={title}
      description={detail}
      className="min-h-[16rem]"
    />
  );
}

export function variableNames(text: string): string[] {
  return Array.from(text.matchAll(/\{\{\s*([a-zA-Z0-9_ -]+)\s*\}\}/g))
    .map((match) => match[1]?.trim())
    .filter((value): value is string => Boolean(value))
    .filter((value, index, arr) => arr.indexOf(value) === index);
}
