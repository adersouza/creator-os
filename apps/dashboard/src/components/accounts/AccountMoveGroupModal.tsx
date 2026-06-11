import { Check } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import type { FleetGroupMeta } from '@/hooks/useFleetAccounts';
import { UNASSIGNED_COLOR } from './shared';

interface AccountMoveGroupModalProps {
  open: boolean;
  count: number;
  groups: FleetGroupMeta[];
  selection: string | null;
  onSelectionChange: (value: string | null) => void;
  onClose: () => void;
  onConfirm: () => void;
}

export function AccountMoveGroupModal({
  open,
  count,
  groups,
  selection,
  onSelectionChange,
  onClose,
  onConfirm,
}: AccountMoveGroupModalProps) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Move ${count} account${count === 1 ? '' : 's'} to group`}
      description="Pick a destination, or unassign to pull them out of every group."
      footer={
        <>
          <Button
            type="button"
            onClick={onClose}
            variant="outline"
            size="sm"
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={onConfirm}
            size="sm"
          >
            {selection ? 'Move' : 'Unassign'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-1 max-h-[50vh] overflow-y-auto">
        <GroupOption
          selected={selection === null}
          color={UNASSIGNED_COLOR}
          label="Unassigned"
          onClick={() => onSelectionChange(null)}
        />
        {groups.map((group) => (
          <GroupOption
            key={group.id}
            selected={selection === group.id}
            color={group.color}
            label={group.name}
            onClick={() => onSelectionChange(group.id)}
          />
        ))}
      </div>
    </Modal>
  );
}

function GroupOption({
  selected,
  color,
  label,
  onClick,
}: {
  selected: boolean;
  color: string;
  label: string;
  onClick: () => void;
}) {
  return (
    <Button
      type="button"
      onClick={onClick}
      variant={selected ? 'secondary' : 'ghost'}
      className="w-full justify-start gap-2.5 px-3 text-left"
    >
      <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: color }} aria-hidden="true" />
      <span className="flex-1 text-[0.8125rem] text-foreground truncate">{label}</span>
      {selected && <Check className="w-3.5 h-3.5 text-foreground shrink-0" aria-hidden="true" />}
    </Button>
  );
}
