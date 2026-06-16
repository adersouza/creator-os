import type React from "react";
import { MatrixLoader, type MatrixLoaderProps } from "@/components/ui/MatrixLoader";
import { cn } from "@/lib/utils";

export interface ProcessingStateProps extends React.HTMLAttributes<HTMLDivElement> {
	label: React.ReactNode;
	description?: React.ReactNode;
	size?: MatrixLoaderProps["size"];
	tone?: MatrixLoaderProps["tone"];
	active?: boolean;
	inline?: boolean;
}

export function ProcessingState({
	label,
	description,
	size = "md",
	tone = "default",
	active = true,
	inline = false,
	className,
	...props
}: ProcessingStateProps) {
	return (
		<div
			role="status"
			aria-live="polite"
			className={cn(
				"flex min-w-0 items-center gap-3 text-sm text-muted-foreground",
				inline ? "inline-flex" : "rounded-lg border border-border bg-muted/35 p-3",
				className,
			)}
			{...props}
		>
			<MatrixLoader
				label={typeof label === "string" ? label : "Processing"}
				size={size}
				tone={tone}
				active={active}
				role="presentation"
				aria-hidden="true"
				className="shrink-0"
			/>
			<span className="min-w-0">
				<span className="block truncate font-medium text-foreground">{label}</span>
				{description ? (
					<span className="mt-0.5 block text-xs leading-snug text-muted-foreground">
						{description}
					</span>
				) : null}
			</span>
		</div>
	);
}
