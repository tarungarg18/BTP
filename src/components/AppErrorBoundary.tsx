import { Component, type ReactNode } from 'react'
import { AlertTriangle, RotateCcw } from 'lucide-react'

interface AppErrorBoundaryProps {
  children: ReactNode
}

interface AppErrorBoundaryState {
  hasError: boolean
}

class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  public state: AppErrorBoundaryState = { hasError: false }

  public static getDerivedStateFromError(): AppErrorBoundaryState {
    return { hasError: true }
  }

  public render(): ReactNode {
    if (!this.state.hasError) return this.props.children

    return (
      <main className="fatal-error">
        <div>
          <AlertTriangle size={30} aria-hidden="true" />
          <p className="eyebrow">Workspace interrupted</p>
          <h1>The GIS interface could not be loaded</h1>
          <p>Check your connection to the map tile service, then reload the application.</p>
          <button type="button" onClick={() => window.location.reload()}>
            <RotateCcw size={16} aria-hidden="true" />
            Reload workspace
          </button>
        </div>
      </main>
    )
  }
}

export default AppErrorBoundary
