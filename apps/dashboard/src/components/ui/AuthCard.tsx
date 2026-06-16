import type React from "react";
import {
	Card,
	CardContent,
	CardDescription,
	CardFooter,
	CardHeader,
	CardTitle,
} from "@/components/ui/Card";
import { cn } from "@/lib/utils";

export interface AuthCardProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
	eyebrow?: React.ReactNode | undefined;
	title: React.ReactNode;
	description?: React.ReactNode | undefined;
	icon?: React.ReactNode | undefined;
	footer?: React.ReactNode | undefined;
	contentClassName?: string | undefined;
}

export function AuthCard({
	eyebrow,
	title,
	description,
	icon,
	footer,
	children,
	className,
	contentClassName,
	...props
}: AuthCardProps) {
	return (
		<Card
			className={cn(
				"auth-card w-full max-w-[28rem] rounded-xl border-border bg-card shadow-sm",
				className,
			)}
			{...props}
		>
			<CardHeader className="flex flex-col items-start gap-3 p-5 pb-4 text-left sm:p-6 sm:pb-4">
				{icon ? (
					<div className="flex size-10 items-center justify-center rounded-lg border border-border bg-muted text-primary shadow-sm">
						{icon}
					</div>
				) : null}
				<div className="min-w-0">
					{eyebrow ? (
						<div className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-primary">
							{eyebrow}
						</div>
					) : null}
					<CardTitle className="text-balance text-2xl font-semibold leading-tight tracking-normal text-foreground">
						{title}
					</CardTitle>
					{description ? (
						<CardDescription className="mt-2 max-w-sm text-sm leading-snug text-muted-foreground">
							{description}
						</CardDescription>
					) : null}
				</div>
			</CardHeader>
			{children ? (
				<CardContent className={cn("p-5 pt-0 sm:p-6 sm:pt-0", contentClassName)}>
					{children}
				</CardContent>
			) : null}
			{footer ? (
				<CardFooter className="justify-start border-t border-border bg-muted/45 p-4 text-left text-xs leading-relaxed text-muted-foreground sm:px-6">
					{footer}
				</CardFooter>
			) : null}
		</Card>
	);
}
