import { Input } from "@/components/ui/Input";
import { Badge } from "@/components/ui/Badge";
import { Field } from "@/components/ui/Field";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import type { SmartLink } from "./types";

type PixelKey = "meta" | "tiktok" | "pinterest" | "google";

const PIXELS: Array<{ key: PixelKey; label: string; placeholder: string }> = [
	{ key: "meta", label: "Meta Pixel ID", placeholder: "123456789012345" },
	{ key: "tiktok", label: "TikTok Pixel ID", placeholder: "CABCDE12345FGHIJ" },
	{ key: "pinterest", label: "Pinterest Tag ID", placeholder: "2612345678901" },
	{ key: "google", label: "Google Tag ID", placeholder: "G-XXXXXXXXXX" },
];

function pixelsFrom(metadata: SmartLink["metadata"]) {
	const pixels =
		metadata?.pixels && typeof metadata.pixels === "object"
			? (metadata.pixels as Record<string, unknown>)
			: {};
	return pixels;
}

export function PixelExtensionsPanel({
	metadata,
	onChange,
}: {
	metadata: SmartLink["metadata"];
	onChange: (metadata: Record<string, unknown>) => void;
}) {
	const pixels = pixelsFrom(metadata);

	const updatePixel = (key: PixelKey, value: string) => {
		onChange({
			...(metadata ?? {}),
			pixels: {
				...pixels,
				[key]: value.trim(),
			},
		});
	};

	return (
		<NovaCard
			className="mt-4"
			variant="panel"
			title="Conversion tracking"
			description="Stored in smart link metadata and injected on public page render."
			action={<Badge tone="outline">Pixels</Badge>}
		>
			<div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
				{PIXELS.map((pixel) => {
					const value =
						typeof pixels[pixel.key] === "string"
							? String(pixels[pixel.key])
							: "";
					return (
						<Field key={pixel.key} label={pixel.label}>
							<Input
								value={value}
								onChange={(event) => updatePixel(pixel.key, event.target.value)}
								placeholder={pixel.placeholder}
								className="font-mono"
							/>
						</Field>
					);
				})}
			</div>
		</NovaCard>
	);
}
