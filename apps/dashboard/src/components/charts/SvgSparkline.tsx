import { useId, useMemo } from 'react';
import { chartTheme } from '@/lib/chartTheme';

interface SvgSparklineProps {
  data: number[];
  stroke?: string | undefined;
  fill?: string | undefined;
  width?: number | undefined;
  height?: number | undefined;
  strokeWidth?: number | undefined;
  ariaLabel?: string | undefined;
}

export function SvgSparkline({
  data,
  stroke = chartTheme.sparkline.stroke,
  fill,
  width = 120,
  height = 36,
  strokeWidth = chartTheme.sparkline.strokeWidth,
  ariaLabel = 'Trend sparkline',
}: SvgSparklineProps) {
  const gradientId = useId().replace(/:/g, '');
  const path = useMemo(() => {
    if (data.length < 2) return '';
    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;
    return data
      .map((value, index) => {
        const x = (index / (data.length - 1)) * width;
        const y = height - ((value - min) / range) * height;
        return `${index === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(' ');
  }, [data, height, width]);

  if (!path) return null;

  const areaPath = `${path} L${width},${height} L0,${height} Z`;
  const fillPaint = fill ?? stroke;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height="100%"
      preserveAspectRatio="none"
      role="img"
      aria-label={ariaLabel}
    >
      <defs>
        <linearGradient id={`svg-sparkline-${gradientId}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={fillPaint} stopOpacity={chartTheme.sparkline.fillOpacity} />
          <stop offset="100%" stopColor={fillPaint} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#svg-sparkline-${gradientId})`} />
      <path d={path} fill="none" stroke={stroke} strokeWidth={strokeWidth} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
