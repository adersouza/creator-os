import { FlaskConical } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";

export function BetaProgramTab() {
	return (
		<div className="flex flex-col gap-8">
			<div>
				<h1 className="text-2xl font-semibold text-foreground dark:text-foreground mb-2 flex items-center gap-2">
					Labs & Experimental{" "}
					<Badge tone="secondary" className="text-[0.625rem] uppercase tracking-wider">
						Beta
					</Badge>
				</h1>
				<p className="text-base text-muted-foreground dark:text-white/50">
					Preview the experimental systems we are testing internally. Self-serve
					enrollment is not available in-product yet.
				</p>
			</div>

			<NovaEmpty
				icon={<FlaskConical data-icon aria-hidden="true" />}
				title="No preview features available yet"
				description="Experimental systems will appear here once they are ready for self-serve enrollment."
			/>
		</div>
	);
}
