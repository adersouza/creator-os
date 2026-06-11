import * as React from "react";
import { Slider as ShadSlider } from "@/components/shadcn/slider";
import { cn } from "@/lib/utils";

export type SliderProps = React.ComponentProps<typeof ShadSlider>;

export const Slider = React.forwardRef<
	React.ElementRef<typeof ShadSlider>,
	SliderProps
>(({ className, ...props }, ref) => {
	return (
		<ShadSlider
			ref={ref}
			className={cn("py-2", className)}
			{...props}
		/>
	);
});
Slider.displayName = "Slider";
