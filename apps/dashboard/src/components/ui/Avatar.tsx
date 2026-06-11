import type * as React from "react";
import {
	Avatar as ShadAvatar,
	AvatarFallback as ShadAvatarFallback,
	AvatarImage as ShadAvatarImage,
} from "@/components/shadcn/avatar";
import { cn } from "@/lib/utils";

function Avatar({
	className,
	...props
}: React.ComponentProps<typeof ShadAvatar>) {
	return (
		<ShadAvatar className={cn("size-10 rounded-full", className)} {...props} />
	);
}

function AvatarImage({
	className,
	loading = "lazy",
	decoding = "async",
	alt = "",
	...props
}: React.ComponentProps<typeof ShadAvatarImage>) {
	return (
		<ShadAvatarImage
			loading={loading}
			decoding={decoding}
			alt={alt}
			className={cn("object-cover", className)}
			{...props}
		/>
	);
}

function AvatarFallback({
	className,
	...props
}: React.ComponentProps<typeof ShadAvatarFallback>) {
	return (
		<ShadAvatarFallback
			className={cn("bg-muted font-medium text-muted-foreground", className)}
			{...props}
		/>
	);
}

export { Avatar, AvatarImage, AvatarFallback };
