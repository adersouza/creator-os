import { Grid2x2, Upload } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaHeader } from "@/components/ui/NovaPrimitives";

export function ContentHero({
	counts,
	onPrimary,
}: {
	counts: { media: number; groups: number };
	onPrimary: () => void;
}) {
	return (
		<NovaHeader
			eyebrow="Media Library"
			title="Content Library"
			meta={`${counts.media} assets · ${counts.groups} groups`}
			description={`${counts.media} media assets ready for scheduling across ${counts.groups} group${counts.groups === 1 ? "" : "s"}.`}
			actions={
				<>
					<Badge tone="outline" className="hidden md:inline-flex">
						<Grid2x2 data-icon="inline-start" />
						Group-ready media
					</Badge>
					<Button type="button" onClick={onPrimary}>
						<Upload data-icon="inline-start" />
						Upload media
					</Button>
				</>
			}
		/>
	);
}
