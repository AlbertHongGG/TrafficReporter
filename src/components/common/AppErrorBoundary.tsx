import React from 'react';
import { AlertCircle } from 'lucide-react';
import { createLogger, serializeError } from '../../utils/logger';

const log = createLogger('AppErrorBoundary');

type AppErrorBoundaryProps = {
  children: React.ReactNode;
};

type AppErrorBoundaryState = {
  hasError: boolean;
  error: Error | null;
  componentStack: string | null;
};

export class AppErrorBoundary extends React.Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = {
    hasError: false,
    error: null,
    componentStack: null,
  };

  static getDerivedStateFromError(error: Error): Partial<AppErrorBoundaryState> {
    return {
      hasError: true,
      error,
    };
  }

  override componentDidCatch(error: Error, info: React.ErrorInfo) {
    this.setState({
      componentStack: info.componentStack ?? null,
    });
    log.error('React render error boundary caught an exception.', {
      error: serializeError(error),
      componentStack: info.componentStack,
    });
  }

  override render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            minHeight: '100vh',
            display: 'grid',
            placeItems: 'center',
            background: '#101217',
            color: '#f8fafc',
            padding: '24px',
            fontFamily: 'ui-monospace, monospace',
          }}
        >
          <div
            style={{
              maxWidth: '800px',
              width: '100%',
              display: 'flex',
              flexDirection: 'column',
              gap: '16px',
              padding: '20px 24px',
              borderRadius: '16px',
              border: '1px solid rgba(248, 113, 113, 0.35)',
              background: 'rgba(20, 24, 31, 0.95)',
              boxShadow: '0 20px 40px rgba(0,0,0,0.5)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', color: '#f87171' }}>
              <AlertCircle size={22} />
              <span style={{ fontWeight: 600, fontSize: '16px' }}>Application UI Error Caught</span>
            </div>
            {this.state.error && (
              <div
                style={{
                  background: 'rgba(0, 0, 0, 0.4)',
                  padding: '12px 16px',
                  borderRadius: '8px',
                  color: '#fca5a5',
                  fontSize: '13px',
                  lineHeight: '1.5',
                  overflowX: 'auto',
                }}
              >
                {this.state.error.toString()}
              </div>
            )}
            {this.state.error?.stack && (
              <details style={{ fontSize: '12px', color: '#94a3b8' }}>
                <summary style={{ cursor: 'pointer', marginBottom: '8px' }}>View Full Stack Trace</summary>
                <pre
                  style={{
                    background: 'rgba(0, 0, 0, 0.5)',
                    padding: '12px',
                    borderRadius: '8px',
                    overflowX: 'auto',
                    whiteSpace: 'pre-wrap',
                    maxHeight: '240px',
                  }}
                >
                  {this.state.error.stack}
                </pre>
              </details>
            )}
            <button
              type="button"
              onClick={() => window.location.reload()}
              style={{
                alignSelf: 'flex-start',
                padding: '8px 16px',
                borderRadius: '8px',
                background: '#334155',
                color: '#fff',
                border: 'none',
                cursor: 'pointer',
                fontSize: '13px',
              }}
            >
              Reload Application
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}