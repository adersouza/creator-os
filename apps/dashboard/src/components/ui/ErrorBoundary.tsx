import React from 'react';
import { captureException } from '@/lib/sentry';
import { Button } from '@/components/ui/Button';
import { NovaCard } from '@/components/ui/NovaPrimitives';

interface Props {
  children: React.ReactNode;
  /** Tag added to the Sentry context — useful when boundaries are nested. */
  scope?: string | undefined;
  /** Custom fallback. When omitted, renders the full-page error screen. */
  fallback?: React.ReactNode | ((error: Error | null, reset: () => void) => React.ReactNode) | undefined;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    captureException(error, {
      react: { componentStack: errorInfo.componentStack ?? '' },
      ...(this.props.scope ? { boundary: { scope: this.props.scope } } : {}),
    });
  }

  reset = (): void => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      const { fallback } = this.props;
      if (fallback !== undefined) {
        return typeof fallback === 'function' ? fallback(this.state.error, this.reset) : fallback;
      }
      return (
        <div className="flex flex-col items-center justify-center min-h-[100dvh] bg-background text-foreground p-8">
          <div className="max-w-md text-center space-y-4">
            <h1 className="text-2xl font-semibold tracking-tight">Something went wrong</h1>
            <p className="text-muted-foreground text-sm">
              An unexpected error occurred. Try refreshing the page.
            </p>
            {this.state.error && (
              <pre className="mt-4 p-4 bg-muted rounded-md text-left text-xs overflow-auto max-h-32 text-muted-foreground">
                {this.state.error.message}
              </pre>
            )}
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="mt-4 px-6 py-2.5 bg-primary text-primary-foreground rounded-md text-sm font-medium hover:opacity-90 transition-opacity"
            >
              Reload Page
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

/**
 * Tile-scoped boundary — when a single dashboard tile crashes (bad hook
 * shape, render-time exception), this keeps the rest of the dashboard
 * alive and shows a tile-sized "tile unavailable" placeholder with a retry.
 */
export function TileErrorBoundary({
  children,
  scope,
  className,
}: {
  children: React.ReactNode;
  /** Sent to Sentry as `boundary.scope` so per-tile errors are grouped. */
  scope?: string | undefined;
  /** Forward the tile's grid-placement classes so the fallback occupies the same slot. */
  className?: string | undefined;
}) {
  return (
    <ErrorBoundary
      scope={scope}
      fallback={(error, reset) => (
        <NovaCard
          className={`flex min-h-[14.5rem] flex-col items-start justify-center gap-2 ${className ?? ''}`}
          contentClassName="flex flex-col items-start justify-center gap-2"
          role="alert"
        >
          <span className="text-sm font-medium text-primary">Tile unavailable</span>
          <p className="text-[0.75rem] leading-relaxed text-muted-foreground">
            This tile failed to render. The rest of the dashboard is unaffected.
          </p>
          {error?.message && (
            <code className="max-w-full break-words font-mono text-[0.625rem] text-muted-foreground opacity-75">
              {error.message.slice(0, 120)}
            </code>
          )}
          <Button
            type="button"
            onClick={reset}
            variant="outline"
            size="sm"
            className="mt-1"
          >
            Retry
          </Button>
        </NovaCard>
      )}
    >
      {children}
    </ErrorBoundary>
  );
}
