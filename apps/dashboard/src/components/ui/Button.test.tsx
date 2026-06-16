import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Button } from './Button';

// Thin smoke test to prove the RTL + jsdom stack renders, clicks land,
// and disabled state gates handlers. Catches the "whole component tree
// broke because React version drifted" class of regressions.
describe('Button', () => {
  const vibrate = vi.fn();

  beforeEach(() => {
    vibrate.mockReset();
    Object.defineProperty(window.navigator, 'vibrate', {
      configurable: true,
      value: vibrate,
    });
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('fires onClick when enabled', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Save</Button>);
    expect(screen.getByRole('button', { name: 'Save' })).toHaveClass('inline-flex');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(onClick).toHaveBeenCalledOnce();
    expect(vibrate).not.toHaveBeenCalled();
  });

  it('swallows clicks when disabled', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Button onClick={onClick} disabled>Save</Button>);
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(onClick).not.toHaveBeenCalled();
    expect(vibrate).not.toHaveBeenCalled();
  });

  it('triggers mapped haptics only when requested', async () => {
    const user = userEvent.setup();
    render(<Button haptic="success">Publish</Button>);

    await user.click(screen.getByRole('button', { name: 'Publish' }));

    expect(vibrate).toHaveBeenCalledWith([10, 50, 10]);
  });

  it('does not trigger haptics when reduced motion is preferred', async () => {
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: query === '(prefers-reduced-motion: reduce)',
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
    const user = userEvent.setup();
    render(<Button haptic="warning">Delete</Button>);

    await user.click(screen.getByRole('button', { name: 'Delete' }));

    expect(vibrate).not.toHaveBeenCalled();
  });

  it('does not trigger haptics when click handlers prevent default', async () => {
    const user = userEvent.setup();
    render(
      <Button haptic="selection" onClick={(event) => event.preventDefault()}>
        Pick
      </Button>,
    );

    await user.click(screen.getByRole('button', { name: 'Pick' }));

    expect(vibrate).not.toHaveBeenCalled();
  });

  it('composes with Radix Slot when asChild is set', () => {
    render(
      <Button asChild>
        <a href="/settings">Settings</a>
      </Button>,
    );

    expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute(
      'href',
      '/settings',
    );
  });
});
