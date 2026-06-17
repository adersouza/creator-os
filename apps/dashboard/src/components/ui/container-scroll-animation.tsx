"use client";
import React, { useRef } from "react";
import { useScroll, useTransform, motion, type MotionValue } from "motion/react";
import { cn } from "@/lib/utils";

export const ContainerScroll = ({
	titleComponent,
	children,
	className,
	cardClassName,
	contentClassName,
	compact = false,
}: {
	titleComponent?: string | React.ReactNode;
	children: React.ReactNode;
	className?: string;
	cardClassName?: string;
	contentClassName?: string;
	compact?: boolean;
}) => {
	const containerRef = useRef<HTMLDivElement>(null);
	const { scrollYProgress } = useScroll({
		target: containerRef,
	});
	const [isMobile, setIsMobile] = React.useState(false);

	React.useEffect(() => {
		const checkMobile = () => {
			setIsMobile(window.innerWidth <= 768);
		};
		checkMobile();
		window.addEventListener("resize", checkMobile);
		return () => {
			window.removeEventListener("resize", checkMobile);
		};
	}, []);

	const scaleDimensions = () => {
		if (compact) return [1, 1];
		return isMobile ? [0.82, 0.96] : [1.04, 1];
	};

	const rotate = useTransform(
		scrollYProgress,
		[0, 1],
		compact ? [0, 0] : [12, 0],
	);
	const scale = useTransform(scrollYProgress, [0, 1], scaleDimensions());
	const translate = useTransform(
		scrollYProgress,
		[0, 1],
		compact ? [0, 0] : [0, -80],
	);

	return (
		<div
			className={cn(
				"relative flex items-center justify-center p-2",
				compact ? "h-auto" : "h-[54rem] md:h-[70rem] md:p-12",
				className,
			)}
			ref={containerRef}
		>
			<div
				className={cn("relative w-full", compact ? "py-0" : "py-10 md:py-32")}
				style={{
					perspective: "1000px",
				}}
			>
				{titleComponent ? (
					<Header translate={translate} titleComponent={titleComponent} />
				) : null}
				<Card
					rotate={rotate}
					translate={translate}
					scale={scale}
					className={cardClassName}
					contentClassName={contentClassName}
				>
					{children}
				</Card>
			</div>
		</div>
	);
};

export const Header = ({
	translate,
	titleComponent,
}: {
	translate: MotionValue<number>;
	titleComponent: React.ReactNode;
}) => {
	return (
		<motion.div
			style={{
				translateY: translate,
			}}
			className="mx-auto max-w-5xl text-center"
		>
			{titleComponent}
		</motion.div>
	);
};

export const Card = ({
	rotate,
	scale,
	children,
	className,
	contentClassName,
}: {
	rotate: MotionValue<number>;
	scale: MotionValue<number>;
	translate: MotionValue<number>;
	children: React.ReactNode;
	className?: string | undefined;
	contentClassName?: string | undefined;
}) => {
	return (
		<motion.div
			style={{
				rotateX: rotate,
				scale,
				boxShadow:
					"0 0 #0000004d, 0 9px 20px #0000004a, 0 37px 37px #00000042, 0 84px 50px #00000026, 0 149px 60px #0000000a, 0 233px 65px #00000003",
			}}
			className={cn(
				"mx-auto w-full rounded-[1.75rem] border border-border bg-card p-2 shadow-2xl",
				className,
			)}
		>
			<div
				className={cn(
					"h-full w-full overflow-hidden rounded-[1.35rem] bg-background",
					contentClassName,
				)}
			>
				{children}
			</div>
		</motion.div>
	);
};
