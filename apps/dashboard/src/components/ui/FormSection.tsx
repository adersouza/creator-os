import type React from "react";
import { NovaCard } from "@/components/ui/NovaPrimitives";

export interface FormSectionProps extends React.ComponentProps<typeof NovaCard> {}

export function FormSection(props: FormSectionProps) {
	return <NovaCard variant="default" {...props} />;
}
