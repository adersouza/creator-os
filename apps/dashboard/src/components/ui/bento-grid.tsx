import { cn } from "@/lib/utils";

export const BentoGrid = ({
	className,
	children,
}: {
	className?: string;
	children?: React.ReactNode;
}) => {
	return (
		<div
			className={cn(
				"mx-auto grid max-w-7xl grid-cols-1 gap-4 md:auto-rows-[18rem] md:grid-cols-3",
				className,
			)}
		>
			{children}
		</div>
	);
};

export const BentoGridItem = ({
	className,
	title,
	description,
	header,
	icon,
}: {
	className?: string;
	title?: string | React.ReactNode;
	description?: string | React.ReactNode;
	header?: React.ReactNode;
	icon?: React.ReactNode;
}) => {
	return (
		<div
			className={cn(
				"group/bento row-span-1 flex min-w-0 flex-col justify-between overflow-hidden rounded-2xl border border-border bg-card p-5 text-card-foreground shadow-sm transition duration-200 hover:-translate-y-0.5 hover:shadow-md",
				className,
			)}
		>
			{header}
			<div className="relative z-10 transition duration-200 group-hover/bento:translate-x-1">
				{icon}
				<div className="mt-3 mb-2 font-sans text-xl font-semibold text-foreground">
					{title}
				</div>
				<div className="font-sans text-sm font-normal leading-6 text-muted-foreground">
					{description}
				</div>
			</div>
		</div>
	);
};
