import type React from "react";
import { NovaCard } from "@/components/ui/NovaPrimitives";

export interface FormSectionProps extends Omit<React.ComponentProps<typeof NovaCard>, "variant"> {}

export function FormSection(props: FormSectionProps) {
	return <NovaCard variant="default" {...props} />;
}
