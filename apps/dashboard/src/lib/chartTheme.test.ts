import { describe, it, expect } from 'vitest';
import { chartTheme, networkColor, seriesStroke } from './chartTheme';

describe('chartTheme — token references', () => {
  it('axis + grid use CSS custom properties (theme-aware)', () => {
    expect(chartTheme.axis.tick).toMatch(/var\(/);
    expect(chartTheme.axis.line).toMatch(/var\(/);
    expect(chartTheme.grid.stroke).toMatch(/var\(/);
  });

  it('tooltip surface tokens fall back to literal hex/rgba so SSR renders before vars resolve', () => {
    expect(chartTheme.tooltip.bg).toContain('var(');
    expect(chartTheme.tooltip.text).toContain('var(');
    expect(chartTheme.tooltip.border).toContain('var(');
  });

  it('tooltip light contentStyle is white-ish and dark is dark-ish', () => {
    expect(chartTheme.tooltip.contentStyle.background).toMatch(/rgba\(255/);
    expect(chartTheme.tooltip.contentStyleDark.background).toMatch(/rgba\(20/);
  });

  it('all four network colors resolve to var() references', () => {
    expect(chartTheme.networks.aurora).toMatch(/var\(/);
    expect(chartTheme.networks.meridian).toMatch(/var\(/);
    expect(chartTheme.networks.harbor).toMatch(/var\(/);
    expect(chartTheme.networks.vale).toMatch(/var\(/);
  });

  it('tickStyle returns SVG-axis-friendly object with custom font size', () => {
    const t = chartTheme.tickStyle(13);
    expect(t.fontSize).toBe(13);
    expect(t.fill).toMatch(/var\(/);
  });

  it('tickStyle defaults to size 10', () => {
    expect(chartTheme.tickStyle().fontSize).toBe(10);
  });
});

describe('networkColor', () => {
  it.each(['aurora', 'meridian', 'harbor', 'vale'] as const)(
    'returns var() reference for %s',
    (n) => {
      expect(networkColor(n)).toMatch(/^var\(/);
    },
  );
});

describe('seriesStroke', () => {
  it('index 0 is solid (no dash)', () => {
    const s = seriesStroke(0);
    expect(s.strokeDasharray).toBeUndefined();
    expect(s.stroke).toMatch(/var\(/);
  });

  it('index 1+ is dashed for colorblind/grayscale legibility', () => {
    expect(seriesStroke(1).strokeDasharray).toBeDefined();
    expect(seriesStroke(2).strokeDasharray).toBeDefined();
    expect(seriesStroke(3).strokeDasharray).toBeDefined();
  });

  it('wraps modulo 4', () => {
    expect(seriesStroke(4)).toEqual(seriesStroke(0));
    expect(seriesStroke(5)).toEqual(seriesStroke(1));
  });
});
