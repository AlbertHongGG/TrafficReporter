import React from 'react';
import { AlertCircle } from 'lucide-react';
import { createLogger, serializeError } from '../utils/logger';

const log = createLogger('AppErrorBoundary');

type AppErrorBoundaryProps = {
  children: React.ReactNode;
};

type AppErrorBoundaryState = {
  hasError: boolean;
};

export class AppErrorBoundary extends React.Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = {
    hasError: false,
  };

  static getDerivedStateFromError() {
    return {
      hasError: true,
    };
  }

  override componentDidCatch(error: Error, info: React.ErrorInfo) {
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
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              padding: '16px 18px',
              borderRadius: '16px',
              border: '1px solid rgba(248, 113, 113, 0.24)',
              background: 'rgba(20, 24, 31, 0.92)',
            }}
          >
            <AlertCircle size={18} />
            <span>The app hit a fatal UI error. Check DevTools console for the full stack trace.</span>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}