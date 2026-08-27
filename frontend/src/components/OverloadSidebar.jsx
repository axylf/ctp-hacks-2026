import { AlertTriangle, Inbox, X } from 'lucide-react';

/**
 * Workload sidebar — empty until real overload data exists.
 * No hardcoded crunch warnings or Gemini lecture plans.
 */
export default function OverloadSidebar({
  open,
  onClose,
  recommendations = [],
  assignments = [],
}) {
  const hasData = recommendations.length > 0 || assignments.length > 0;

  return (
    <>
      <div
        className={`sidebar-overlay${open ? ' open' : ''}`}
        onClick={onClose}
        aria-hidden={!open}
      />

      <aside
        className={`sidebar${open ? ' open' : ''}`}
        aria-label="Workload insights"
      >
        <div className="sidebar-header">
          <h2>
            <AlertTriangle size={18} color="var(--crimson-600)" />
            Workload Insights
          </h2>
          <button
            type="button"
            className="sidebar-close"
            onClick={onClose}
            aria-label="Close sidebar"
          >
            <X size={18} />
          </button>
        </div>

        {!hasData ? (
          <div className="sidebar-empty">
            <Inbox size={28} strokeWidth={1.5} />
            <p>
              No overload alerts yet. This panel stays empty until real
              deadlines exist — nothing is hardcoded.
            </p>
          </div>
        ) : null}
      </aside>
    </>
  );
}
