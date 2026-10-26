import { Component } from 'react';

/**
 * Catches render errors so one broken component does not blank the whole app.
 *
 * Without this, an exception inside the meeting room unmounts the entire React
 * tree and the user gets a white page — mid-call, with no way back and no idea
 * what happened. A visible, explained failure with a working "reload" button is
 * a far better outcome, and for an accessibility tool it is the difference
 * between a hiccup and being cut off from the conversation.
 *
 * This has to be a class component: error boundaries are one of the few things
 * React hooks still cannot express.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Keep the stack in the console for whoever is debugging. A production
    // deployment would forward this to an error tracker instead.
    console.error('Unhandled error in React tree', error, info);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <main className="grid min-h-screen place-items-center bg-light-surface p-6">
        <div className="card max-w-lg p-6 shadow-dialog" role="alert">
          <h1 className="text-xl font-medium text-light-text">Something went wrong</h1>

          <p className="mt-2 text-sm text-light-muted">
            BridgeTalk hit an unexpected error and stopped rendering this screen.
            Your meeting has not been deleted — reloading usually recovers it.
          </p>

          <pre className="mt-4 overflow-x-auto rounded-card bg-light-surface p-3 text-xs text-light-muted">
            {error.message}
          </pre>

          <div className="mt-4 flex gap-2">
            <button type="button" onClick={() => window.location.reload()}
                    className="btn-primary">
              Reload
            </button>
            <button type="button" onClick={() => { window.location.href = '/'; }}
                    className="btn-outlined">
              Back to home
            </button>
          </div>
        </div>
      </main>
    );
  }
}
