import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { axe, toHaveNoViolations } from 'jest-axe';
import { Button } from './Button';
import { StatusPill } from './StatusPill';

expect.extend(toHaveNoViolations);

// A11y smoke net over the primitives that show up on every page. Catches
// the "we added a div wrapper with no label" class of regression the
// moment CI runs. Expand as primitives land.
describe('a11y: primitives', () => {
  it('Button default has no violations', async () => {
    const { container } = render(<Button>Save changes</Button>);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it('Button disabled has no violations', async () => {
    const { container } = render(<Button disabled>Save changes</Button>);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it('StatusPill with live dot has no violations', async () => {
    const { container } = render(
      <StatusPill tone="good" dot live>
        Online
      </StatusPill>,
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
