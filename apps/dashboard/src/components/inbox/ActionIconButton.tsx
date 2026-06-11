import type React from 'react';
import { Button } from "@/components/ui/Button";
import { Kbd } from './helpers';

export function ActionIconButton({
  icon: Icon,
  label,
  kbd,
  onClick,
}: {
  icon: React.ComponentType<{ className?: string | undefined }>;
  label: string;
  kbd?: string | undefined;
  onClick?: (() => void) | undefined;
}) {
  return (
    <Button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={kbd ? `${label} (${kbd})` : label}
      variant="ghost"
      size="sm"
      className="h-8 px-2.5 text-[0.75rem]"
    >
      <Icon aria-hidden="true" />
      <span className="hidden md:inline">{label}</span>
      {kbd && <Kbd>{kbd}</Kbd>}
    </Button>
  );
}
