import { useEffect, useRef, useState, type ReactElement, type ReactNode } from "react";
import {
	Area,
	AreaChart as RechartsAreaChart,
	Bar,
	BarChart as RechartsBarChart,
	CartesianGrid,
	Cell,
	ReferenceLine,
	Tooltip as RechartsTooltip,
	XAxis,
	YAxis,
	ResponsiveContainer,
} from "recharts";
import { cn } from "@/lib/utils";

export interface JunoChartContainerProps {
	children: ReactElement | ReactNode;
	ariaLabel: string;
	className?: string | undefined;
	minHeightClassName?: string | undefined;
	height?: number | undefined;
	variant?:
		| "default"
		| "routine-area"
		| "routine-line"
		| "routine-bar"
		| "source-mix"
		| "radial-score"
		| "funnel-flow"
		| "sankey-flow"
		| undefined;
}

export function JunoChartContainer({
	children,
	ariaLabel,
	className,
	minHeightClassName = "min-h-[220px] sm:min-h-[240px]",
	height = 240,
	variant = "default",
}: JunoChartContainerProps) {
	const containerRef = useRef<HTMLDivElement | null>(null);
	const [width, setWidth] = useState(0);

	useEffect(() => {
		const node = containerRef.current;
		if (!node) return;

		const updateWidth = () => {
			const nextWidth = Math.floor(node.getBoundingClientRect().width);
			setWidth((current) => (current === nextWidth ? current : nextWidth));
		};

		updateWidth();
		if (typeof ResizeObserver === "undefined") {
			window.addEventListener("resize", updateWidth);
			return () => window.removeEventListener("resize", updateWidth);
		}

		const observer = new ResizeObserver(updateWidth);
		observer.observe(node);
		return () => observer.disconnect();
	}, []);

	return (
		<div
			ref={containerRef}
			role="img"
			aria-label={ariaLabel}
			data-chart-variant={variant}
			data-chart-ready={width > 0 ? "true" : "false"}
			className={cn(
				"juno-chart-container w-full overflow-hidden rounded-lg",
				variant !== "default" && "border border-border/70 bg-muted/35",
				(variant === "source-mix" || variant === "funnel-flow") &&
					"bg-[linear-gradient(180deg,color-mix(in_srgb,var(--color-muted)_60%,var(--color-card)),color-mix(in_srgb,var(--color-card)_92%,var(--color-muted)))]",
				(variant === "radial-score" || variant === "sankey-flow") &&
					"bg-[radial-gradient(circle_at_center,color-mix(in_srgb,var(--color-muted)_60%,var(--color-card)),color-mix(in_srgb,var(--color-card)_94%,var(--color-muted))_62%)]",
				minHeightClassName,
				className,
			)}
			style={{ height }}
		>
			{width > 0 ? (
				<ResponsiveContainer width={width} height={height}>
					{children as ReactElement}
				</ResponsiveContainer>
			) : null}
		</div>
	);
}

interface JunoTooltipPayload {
	name?: ReactNode | undefined;
	value?: unknown;
	color?: string | undefined;
	dataKey?: unknown;
	payload?: unknown;
}

export interface JunoChartTooltipProps {
	active?: boolean | undefined;
	label?: ReactNode | undefined;
	payload?: ReadonlyArray<JunoTooltipPayload> | undefined;
	valueSuffix?: string | undefined;
	valueFormatter?: ((value: number | string) => ReactNode) | undefined;
}

export function JunoChartTooltip({
	active,
	label,
	payload,
	valueSuffix = "%",
	valueFormatter,
}: JunoChartTooltipProps) {
	if (!active || !payload || payload.length === 0) return null;

	return (
		<div className="juno-chart-tooltip rounded-lg border border-border bg-popover/95 px-3 py-2 text-[0.75rem] shadow-xl backdrop-blur">
			{label ? <div className="font-medium text-foreground">{label}</div> : null}
			<div className="mt-1 grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5">
				{payload.map((item) => {
					const value =
						typeof item.value === "number"
							? valueFormatter
								? valueFormatter(item.value)
								: `${item.value.toFixed(1)}${valueSuffix}`
							: valueFormatter
								? valueFormatter(String(item.value ?? ""))
								: Array.isArray(item.value)
									? item.value.join(", ")
									: String(item.value ?? "");
					return (
						<span key={String(item.dataKey ?? item.name)} className="contents">
							<span className="inline-flex items-center gap-1.5 text-muted-foreground">
								<span
									aria-hidden="true"
									className="size-2 rounded-full"
									style={{ backgroundColor: item.color }}
								/>
								{item.name}
							</span>
							<span className="text-right tabular-nums text-foreground">
								{value}
							</span>
						</span>
					);
				})}
			</div>
		</div>
	);
}

export interface JunoBarChartDatum {
	label: string;
	value: number;
	name?: string | undefined;
}

export interface JunoBarChartProps {
	data: JunoBarChartDatum[];
	ariaLabel: string;
	height?: number | undefined;
	valueLabel?: string | undefined;
	valueFormatter?: ((value: number) => ReactNode) | undefined;
	fill?: string | undefined;
	className?: string | undefined;
}

export interface JunoComparisonBarDatum {
	label: string;
	current: number;
	previous: number;
}

export interface JunoComparisonBarChartProps {
	data: JunoComparisonBarDatum[];
	ariaLabel: string;
	height?: number | undefined;
	currentLabel?: string | undefined;
	previousLabel?: string | undefined;
	valueFormatter?: ((value: number) => ReactNode) | undefined;
	className?: string | undefined;
}

export interface JunoDeltaBarDatum {
	label: string;
	gain: number;
	loss: number;
}

export interface JunoDeltaBarChartProps {
	data: JunoDeltaBarDatum[];
	ariaLabel: string;
	height?: number | undefined;
	maxMagnitude?: number | undefined;
	valueFormatter?: ((value: number) => ReactNode) | undefined;
	className?: string | undefined;
}

export interface JunoShareBarDatum {
	label: string;
	pct: number;
	color: string;
}

export interface JunoShareBarChartProps {
	data: JunoShareBarDatum[];
	ariaLabel: string;
	height?: number | undefined;
	className?: string | undefined;
}

export interface JunoAreaSeries {
	key: string;
	label: string;
	color: string;
}

export interface JunoStackedAreaChartProps {
	data: Array<Record<string, number | string>>;
	series: JunoAreaSeries[];
	ariaLabel: string;
	height?: number | undefined;
	xKey?: string | undefined;
	className?: string | undefined;
	valueSuffix?: string | undefined;
	valueFormatter?: ((value: number | string) => ReactNode) | undefined;
	xTickFormatter?: ((value: string) => string) | undefined;
	tooltipLabelFormatter?: ((value: string) => ReactNode) | undefined;
	percentage?: boolean | undefined;
}

export function JunoBarChart({
	data,
	ariaLabel,
	height = 268,
	valueLabel = "Value",
	valueFormatter,
	fill = "var(--color-chart-2)",
	className,
}: JunoBarChartProps) {
	const formatter = valueFormatter ?? ((value: number) => `${value}`);
	const axisFormatter = (value: unknown) => String(formatter(Number(value)) ?? "");

	return (
		<JunoChartContainer
			ariaLabel={ariaLabel}
			variant="routine-bar"
			height={height}
			minHeightClassName={height === 268 ? "min-h-[268px]" : undefined}
			className={className}
		>
			<RechartsBarChart
				data={data}
				margin={{ top: 18, right: 14, left: -18, bottom: 4 }}
			>
				<CartesianGrid vertical={false} />
				<XAxis
					dataKey="label"
					axisLine={false}
					tickLine={false}
					interval="preserveStartEnd"
				/>
				<YAxis
					axisLine={false}
					tickLine={false}
					tickFormatter={axisFormatter}
					width={56}
				/>
				<RechartsTooltip
					cursor={{ fill: "var(--color-muted)", opacity: 0.35 }}
					content={
						<JunoChartTooltip
							valueSuffix=""
							valueFormatter={(value) => formatter(Number(value))}
						/>
					}
				/>
				<Bar
					dataKey="value"
					name={valueLabel}
					fill={fill}
					radius={[7, 7, 0, 0]}
					maxBarSize={44}
				/>
			</RechartsBarChart>
		</JunoChartContainer>
	);
}

export function JunoComparisonBarChart({
	data,
	ariaLabel,
	height = 190,
	currentLabel = "Current",
	previousLabel = "Prior",
	valueFormatter,
	className,
}: JunoComparisonBarChartProps) {
	const formatter = valueFormatter ?? ((value: number) => `${value}`);

	return (
		<JunoChartContainer
			ariaLabel={ariaLabel}
			variant="routine-bar"
			height={height}
			minHeightClassName={height === 190 ? "min-h-[190px]" : undefined}
			className={className}
		>
			<RechartsBarChart
				data={data}
				layout="vertical"
				margin={{ top: 4, right: 10, bottom: 0, left: 0 }}
				barGap={4}
			>
				<CartesianGrid horizontal={false} />
				<XAxis
					type="number"
					axisLine={false}
					tickLine={false}
					tickFormatter={(value) => String(formatter(Number(value)) ?? "")}
				/>
				<YAxis
					type="category"
					dataKey="label"
					width={72}
					axisLine={false}
					tickLine={false}
				/>
				<RechartsTooltip
					cursor={{ fill: "var(--color-muted)", opacity: 0.35 }}
					content={
						<JunoChartTooltip
							valueSuffix=""
							valueFormatter={(value) => formatter(Number(value))}
						/>
					}
				/>
				<Bar
					dataKey="previous"
					name={previousLabel}
					fill="var(--color-chart-4)"
					fillOpacity={0.35}
					radius={[0, 6, 6, 0]}
				/>
				<Bar
					dataKey="current"
					name={currentLabel}
					fill="var(--color-chart-1)"
					radius={[0, 6, 6, 0]}
				/>
			</RechartsBarChart>
		</JunoChartContainer>
	);
}

export function JunoDeltaBarChart({
	data,
	ariaLabel,
	height = 126,
	maxMagnitude,
	valueFormatter,
	className,
}: JunoDeltaBarChartProps) {
	const domainMax =
		maxMagnitude ?? Math.max(...data.map((row) => Math.abs(row.gain)), ...data.map((row) => Math.abs(row.loss)), 1);

	return (
		<JunoChartContainer
			ariaLabel={ariaLabel}
			variant="routine-bar"
			height={height}
			minHeightClassName={height === 126 ? "min-h-[126px]" : undefined}
			className={className}
		>
			<RechartsBarChart
				data={data}
				margin={{ top: 4, right: 2, bottom: 0, left: 2 }}
			>
				<CartesianGrid vertical={false} />
				<XAxis dataKey="label" hide />
				<YAxis hide domain={[-domainMax, domainMax]} />
				<RechartsTooltip
					content={
						<JunoChartTooltip
							valueSuffix=""
							valueFormatter={(value) =>
								valueFormatter
									? valueFormatter(Math.abs(Number(value)))
									: String(Math.abs(Number(value)))
							}
						/>
					}
					cursor={{ fill: "var(--color-muted)", opacity: 0.18 }}
				/>
				<ReferenceLine y={0} stroke="var(--color-border)" />
				<Bar
					dataKey="gain"
					name="Gains"
					fill="var(--color-health-good)"
					radius={[4, 4, 0, 0]}
				/>
				<Bar
					dataKey="loss"
					name="Losses"
					fill="var(--color-chart-danger)"
					fillOpacity={0.72}
					radius={[0, 0, 4, 4]}
				/>
			</RechartsBarChart>
		</JunoChartContainer>
	);
}

export function JunoShareBarChart({
	data,
	ariaLabel,
	height = 124,
	className,
}: JunoShareBarChartProps) {
	return (
		<JunoChartContainer
			ariaLabel={ariaLabel}
			variant="routine-bar"
			height={height}
			minHeightClassName={height === 124 ? "min-h-[124px]" : undefined}
			className={className}
		>
			<RechartsBarChart
				data={data}
				layout="vertical"
				margin={{ top: 4, right: 8, bottom: 0, left: 4 }}
			>
				<CartesianGrid horizontal={false} />
				<XAxis type="number" hide domain={[0, 100]} />
				<YAxis
					type="category"
					dataKey="label"
					width={82}
					tickLine={false}
					axisLine={false}
				/>
				<RechartsTooltip content={<JunoChartTooltip />} cursor={false} />
				<Bar dataKey="pct" name="Share" radius={[0, 6, 6, 0]} barSize={12}>
					{data.map((row) => (
						<Cell key={row.label} fill={row.color} />
					))}
				</Bar>
			</RechartsBarChart>
		</JunoChartContainer>
	);
}

export function JunoStackedAreaChart({
	data,
	series,
	ariaLabel,
	height = 260,
	xKey = "label",
	className,
	valueSuffix = "%",
	valueFormatter,
	xTickFormatter,
	tooltipLabelFormatter,
	percentage = true,
}: JunoStackedAreaChartProps) {
	return (
		<JunoChartContainer
			ariaLabel={ariaLabel}
			variant="source-mix"
			height={height}
			minHeightClassName={height === 260 ? "min-h-[260px]" : undefined}
			className={className}
		>
			<RechartsAreaChart
				data={data}
				margin={{ top: 10, right: 14, bottom: 6, left: -8 }}
			>
				<CartesianGrid vertical={false} strokeDasharray="3 3" />
				<XAxis
					dataKey={xKey}
					axisLine={false}
					tickLine={false}
					minTickGap={24}
					tickFormatter={(value) =>
						xTickFormatter ? xTickFormatter(String(value)) : String(value)
					}
				/>
				<YAxis
					{...(percentage
						? { domain: [0, 100] as [number, number], ticks: [0, 25, 50, 75, 100] }
						: {})}
					axisLine={false}
					tickLine={false}
					width={44}
					tickFormatter={(value) =>
						valueFormatter
							? String(valueFormatter(Number(value)) ?? "")
							: percentage
								? `${value}%`
								: String(value)
					}
				/>
				<RechartsTooltip
					cursor={{ stroke: "var(--color-border)", strokeDasharray: "3 3" }}
					content={({ active, payload, label }) => (
						<JunoChartTooltip
							active={active}
							payload={payload}
							label={
								tooltipLabelFormatter
									? tooltipLabelFormatter(String(label))
									: String(label ?? "")
							}
							valueSuffix={valueSuffix}
							valueFormatter={valueFormatter}
						/>
					)}
				/>
				{series.map((item) => (
					<Area
						key={item.key}
						type="monotone"
						dataKey={item.key}
						name={item.label}
						stackId="juno-area"
						stroke={item.color}
						fill={item.color}
						fillOpacity={0.84}
						strokeOpacity={0.9}
						isAnimationActive={false}
					/>
				))}
			</RechartsAreaChart>
		</JunoChartContainer>
	);
}
