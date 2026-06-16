import { ArrowRight, CalendarCheck, Smartphone } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { trackClientEvent } from "@/services/clientTelemetry";

export function PublishingStartCard({
	surface,
	className = "",
	compact = false,
}: {
	surface: string;
	className?: string | undefined;
	compact?: boolean | undefined;
}) {
	const navigate = useNavigate();
	return (
		<NovaCard
			className={className}
			variant={compact ? "compact" : "default"}
			eyebrow={
				<span className="inline-flex items-center gap-2">
					<CalendarCheck className="h-3.5 w-3.5" aria-hidden="true" />
					First post setup
				</span>
			}
			title={
				compact
					? "Set up the first publish path."
					: "Get from account setup to a scheduled Instagram post."
			}
			description={
				compact
					? "Check phone handoff, media readiness, and scheduling before the first post."
					: "Juno33 will check Instagram connection, Notify Me phone setup, media readiness, and schedule timing before you post."
			}
		>
			<div className="flex flex-wrap items-center justify-end gap-2">
				<Button
					type="button"
					variant="outline"
					size={compact ? "sm" : "md"}
					onClick={() => {
						trackClientEvent("empty_state_cta_clicked", {
							surface,
							cta: "phone_setup",
						});
						navigate("/settings/notifications");
					}}
				>
					<Smartphone data-icon="inline-start" aria-hidden="true" />
					Phone setup
				</Button>
				<Button
					type="button"
					variant="default"
					size={compact ? "sm" : "md"}
					onClick={() => {
						trackClientEvent("empty_state_cta_clicked", {
							surface,
							cta: "first_post_wizard",
						});
						navigate("/setup/publishing");
					}}
				>
					Start here
					<ArrowRight data-icon="inline-end" aria-hidden="true" />
				</Button>
			</div>
		</NovaCard>
	);
}
