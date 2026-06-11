import { Spinner as ShadcnSpinner } from "@/components/shadcn/spinner";
import { cn } from "@/lib/utils";

export function Spinner({
	className,
	...props
}: React.ComponentProps<typeof ShadcnSpinner>) {
	return <ShadcnSpinner className={cn("text-muted-foreground", className)} {...props} />;
}
