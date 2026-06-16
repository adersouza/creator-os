import type React from "react";
import { motion, useReducedMotion, type HTMLMotionProps } from "motion/react";
import { eases, durations, transitions } from "@/lib/motion";
import { cn } from "@/lib/utils";

type MotionTag = "div" | "section" | "article" | "li";

const MOTION_TAG: Record<MotionTag, React.ElementType> = {
	div: motion.div,
	section: motion.section,
	article: motion.article,
	li: motion.li,
};

const STATIC_TAG: Record<MotionTag, React.ElementType> = {
	div: "div",
	section: "section",
	article: "article",
	li: "li",
};

type SharedMotionProps = Omit<
	HTMLMotionProps<"div">,
	"as" | "initial" | "animate" | "exit" | "transition" | "variants"
> & {
	as?: MotionTag;
	disabled?: boolean;
};

export interface MotionRevealProps extends SharedMotionProps {
	delay?: number;
	distance?: number;
}

export function MotionReveal({
	as = "div",
	children,
	className,
	delay = 0,
	distance = 10,
	disabled = false,
	...props
}: MotionRevealProps) {
	const reducedMotion = useReducedMotion();
	const Tag = disabled || reducedMotion ? STATIC_TAG[as] : MOTION_TAG[as];

	if (disabled || reducedMotion) {
		return (
			<Tag className={className} {...props}>
				{children}
			</Tag>
		);
	}

	return (
		<Tag
			initial={{ opacity: 0, y: distance }}
			animate={{ opacity: 1, y: 0 }}
			transition={{
				duration: durations.normal,
				ease: eases.enter,
				delay: Math.min(delay, 0.18),
			}}
			className={className}
			{...props}
		>
			{children}
		</Tag>
	);
}

export interface MotionListProps extends SharedMotionProps {
	stagger?: number;
}

export function MotionList({
	as = "div",
	children,
	className,
	stagger = 0.035,
	disabled = false,
	...props
}: MotionListProps) {
	const reducedMotion = useReducedMotion();
	const Tag = disabled || reducedMotion ? STATIC_TAG[as] : MOTION_TAG[as];

	if (disabled || reducedMotion) {
		return (
			<Tag className={className} {...props}>
				{children}
			</Tag>
		);
	}

	return (
		<Tag
			initial="hidden"
			animate="visible"
			variants={{
				hidden: { opacity: 1 },
				visible: {
					opacity: 1,
					transition: { staggerChildren: Math.min(stagger, 0.05) },
				},
			}}
			className={className}
			{...props}
		>
			{children}
		</Tag>
	);
}

export interface MotionCardProps extends MotionRevealProps {
	interactive?: boolean;
}

export function MotionCard({
	as = "div",
	children,
	className,
	delay = 0,
	distance = 8,
	disabled = false,
	interactive = false,
	...props
}: MotionCardProps) {
	const reducedMotion = useReducedMotion();
	const Tag = reducedMotion || disabled ? STATIC_TAG[as] : MOTION_TAG[as];

	if (reducedMotion || disabled) {
		return (
			<Tag className={className} {...props}>
				{children}
			</Tag>
		);
	}

	return (
		<Tag
			initial={{ opacity: 0, y: distance }}
			animate={{ opacity: 1, y: 0 }}
			whileHover={interactive ? { y: -1 } : undefined}
			whileTap={interactive ? { y: 0 } : undefined}
			transition={{ ...transitions.stagger, delay: Math.min(delay, 0.18) }}
			className={cn(interactive && "will-change-transform", className)}
			{...props}
		>
			{children}
		</Tag>
	);
}
