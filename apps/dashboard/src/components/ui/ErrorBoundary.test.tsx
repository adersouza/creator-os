// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ErrorBoundary, TileErrorBoundary } from './ErrorBoundary';

vi.mock('@/lib/sentry', () => ({
  captureException: vi.fn(),
}));

vi.mock('@/components/ui/Tile', () => ({
  Tile: ({
    children,
    role,
    className,
  }: { children: React.ReactNode; role?: string | undefined; className?: string | undefined }) => (
    <div role={role} className={className}>
      {children}
    </div>
  ),
}));

const Boom = ({ msg = 'kaboom' }: { msg?: string | undefined }) => {
  throw new Error(msg);
};

describe('ErrorBoundary', () => {
  beforeEach(async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const { captureException } = await import('@/lib/sentry');
    (captureException as ReturnType<typeof vi.fn>).mockClear();
  });

  it('renders children when no error thrown', () => {
    render(
      <ErrorBoundary>
        <div>safe content</div>
      </ErrorBoundary>,
    );
    expect(screen.getByText('safe content')).toBeInTheDocument();
  });

  it('renders default full-page fallback when child throws', () => {
    render(
      <ErrorBoundary>
        <Boom msg="caught error" />
      </ErrorBoundary>,
    );
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    expect(screen.getByText('caught error')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reload page/i })).toBeInTheDocument();
  });

  it('renders custom fallback prop when provided', () => {
    render(
      <ErrorBoundary fallback={<span>custom fallback</span>}>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText('custom fallback')).toBeInTheDocument();
  });

  it('passes error + reset to function fallback', () => {
    const fallbackFn = vi.fn((_error: Error | null, _reset: () => void) => (
      <span>fn fallback</span>
    ));
    render(
      <ErrorBoundary fallback={fallbackFn}>
        <Boom msg="forwarded" />
      </ErrorBoundary>,
    );
    expect(fallbackFn).toHaveBeenCalled();
    const [errArg, resetArg] = fallbackFn.mock.calls[0]!;
    expect(errArg).toBeInstanceOf(Error);
    expect((errArg as Error).message).toBe('forwarded');
    expect(typeof resetArg).toBe('function');
  });

  it('Sentry capture is invoked when child throws', async () => {
    const { captureException } = await import('@/lib/sentry');
    render(
      <ErrorBoundary scope="test-scope">
        <Boom msg="scoped" />
      </ErrorBoundary>,
    );
    expect(captureException).toHaveBeenCalled();
    const errArg = (captureException as ReturnType<typeof vi.fn>).mock.calls[0]![0];
    expect(errArg).toBeInstanceOf(Error);
    expect((errArg as Error).message).toBe('scoped');
  });
});

describe('TileErrorBoundary', () => {
  beforeEach(async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const { captureException } = await import('@/lib/sentry');
    (captureException as ReturnType<typeof vi.fn>).mockClear();
  });

  it('renders tile fallback with retry button on child error', () => {
    render(
      <TileErrorBoundary scope="tile-test">
        <Boom msg="tile crash" />
      </TileErrorBoundary>,
    );
    expect(screen.getByText('Tile unavailable')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('shows truncated error message in fallback', () => {
    const longMsg = 'x'.repeat(200);
    render(
      <TileErrorBoundary>
        <Boom msg={longMsg} />
      </TileErrorBoundary>,
    );
    const code = screen.getByText(/^x+$/);
    expect(code.textContent?.length).toBeLessThanOrEqual(120);
  });

  it('forwards className for grid placement', () => {
    const { container } = render(
      <TileErrorBoundary className="dashboard-grid-slot">
        <Boom />
      </TileErrorBoundary>,
    );
    expect(container.querySelector('.dashboard-grid-slot')).toBeInTheDocument();
  });
});
