import { UserPlus, Check, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { useInboxAssignments } from "@/hooks/useInboxAssignments";
import { useWorkspaceStore } from "@/stores/useWorkspaceStore";
import type { WorkspaceMember } from "@/types/team";
import { appToast } from "@/lib/toast";
import {
	DropdownMenuRoot,
	DropdownMenuTrigger,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuLabel,
	DropdownMenuSeparator,
} from "@/components/ui/DropdownMenu";
import { Avatar, AvatarFallback } from "@/components/ui/Avatar";

/**
 * Assignment chip for an inbox conversation. Shows who owns the triage for
 * a given message; clicking opens a roster of workspace members so anyone
 * with edit permission can hand it off. Backed by useInboxAssignments()
 * (realtime) — the chip updates live if a teammate assigns themselves
 * from another device.
 */
export function AssignmentChip({
	source,
	messageId,
}: {
	source: string;
	messageId: string;
}) {
	const { getAssignment, assign, unassign, hasError } = useInboxAssignments();
	const members = useWorkspaceStore((s) => s.members);

	const assignment = getAssignment(source, messageId);
	const assignedMember = assignment
		? members.find((m) => m.userId === assignment.assigned_to)
		: null;

	const handleAssign = async (member: WorkspaceMember) => {
		const ok = await assign(source, messageId, member.userId);
		if (!ok) appToast.error("Could not assign. Try again.");
	};

	const handleUnassign = async () => {
		const ok = await unassign(source, messageId);
		if (!ok) appToast.error("Could not unassign.");
	};

	return (
		<DropdownMenuRoot>
			<DropdownMenuTrigger asChild>
				<Button
					type="button"
					disabled={hasError}
					aria-label={
						hasError
							? "Assignments unavailable"
							: assignedMember
								? `Assigned to ${assignedMember.displayName || assignedMember.email}`
								: "Assign"
					}
					variant={assignedMember ? "secondary" : "outline"}
					size="sm"
					className={cn(
						"h-8 px-2 text-[0.71875rem]",
						hasError
							? "cursor-not-allowed text-muted-foreground"
							: assignedMember
								? "text-muted-foreground"
								: "border-dashed text-muted-foreground",
					)}
				>
					{hasError ? (
						<>
							<UserPlus aria-hidden="true" />
							<span>Unavailable</span>
						</>
					) : assignedMember ? (
						<>
							<Initial
								name={assignedMember.displayName || assignedMember.email || "?"}
							/>
							<span className="truncate max-w-[100px]">
								{
									(assignedMember.displayName || assignedMember.email)?.split(
										" ",
									)[0]
								}
							</span>
						</>
					) : (
						<>
							<UserPlus aria-hidden="true" />
							<span>Assign</span>
						</>
					)}
				</Button>
			</DropdownMenuTrigger>
			<DropdownMenuContent align="end" className="min-w-[220px]">
				<DropdownMenuLabel>Assign to</DropdownMenuLabel>
				{members.length === 0 ? (
					<div className="px-3 py-2 text-[0.75rem] text-muted-foreground">
						No teammates yet
					</div>
				) : (
					members.map((m) => {
						const isMe = m.userId === assignment?.assigned_to;
						return (
							<DropdownMenuItem
								key={m.userId}
								onSelect={() => void handleAssign(m)}
							>
								<Initial name={m.displayName || m.email || "?"} />
								<span className="flex-1 truncate text-left">
									{m.displayName || m.email}
								</span>
								{isMe && (
									<Check className="size-3 shrink-0 text-muted-foreground" />
								)}
							</DropdownMenuItem>
						);
					})
				)}
				{assignment && (
					<>
						<DropdownMenuSeparator />
						<DropdownMenuItem
							destructive
							onSelect={() => void handleUnassign()}
						>
							<X className="size-3" />
							Unassign
						</DropdownMenuItem>
					</>
				)}
			</DropdownMenuContent>
		</DropdownMenuRoot>
	);
}

function Initial({ name }: { name: string }) {
	const ch = name.charAt(0).toUpperCase();
	return (
		<Avatar
			className="size-4 text-[0.5625rem] text-white"
			style={{
				background:
					"linear-gradient(135deg, var(--color-oxblood) 0%, var(--color-ink) 100%)",
			}}
		>
			<AvatarFallback className="bg-transparent text-white">
				{ch}
			</AvatarFallback>
		</Avatar>
	);
}
