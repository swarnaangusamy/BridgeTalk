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
      <main className="grid min-h-screen place-items-center p-6">
        <div className="panel max-w-lg" role="alert">
          <h1 className="text-2xl font-bold">Something went wrong</h1>

          <p className="mt-2 text-slate-300">
            BridgeTalk hit an unexpected error and stopped rendering this screen.
            Your meeting has not been deleted — reloading usually recovers it.
          </p>

          <pre className="mt-4 overflow-x-auto rounded-lg bg-ink-900 p-3 text-xs text-slate-400">
            {error.message}
          </pre>

          <div className="mt-4 flex gap-2">
            <button type="button" onClick={() => window.location.reload()}
                    className="btn-primary">
              Reload
            </button>
            <button type="button" onClick={() => { window.location.href = '/'; }}
                    className="rounded-lg border border-ink-700 px-4 py-2 hover:bg-ink-700">
              Back to dashboard
            </button>
          </div>
        </div>
      </main>
    );
  }
}
