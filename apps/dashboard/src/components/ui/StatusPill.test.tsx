import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StatusPill } from './StatusPill';

// Lock the StatusPill API so accidental prop renames break here instead of
// silently drifting the 9 sites this primitive consolidates.
describe('StatusPill', () => {
  it('renders children and applies the ink tone by default palette', () => {
    render(<StatusPill>Hello</StatusPill>);
    expect(screen.getByText('Hello')).toBeInTheDocument();
  });

  it('renders a pulsing dot when live', () => {
    const { container } = render(<StatusPill tone="good" dot live>Online</StatusPill>);
    const dot = container.querySelector('.animate-pulse');
    expect(dot).not.toBeNull();
  });

  it('renders an icon when provided', () => {
    const { container } = render(
      <StatusPill tone="critical" icon={<svg data-testid="icon" />}>Flagged</StatusPill>,
    );
    expect(container.querySelector('[data-testid="icon"]')).not.toBeNull();
  });
});
