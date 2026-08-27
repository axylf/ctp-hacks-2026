import { AlertTriangle, Inbox, Sparkles, X } from 'lucide-react';

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
        ) : (
          <>
            {assignments.length > 0 && (
              <div className="risk-card medium">
                <span className="risk-badge medium">Extracted schedule</span>
                <p className="risk-warning">
                  {assignments.length} deadline{assignments.length === 1 ? '' : 's'} are being checked for workload conflicts.
                </p>
              </div>
            )}
            {recommendations.length > 0 && (
              <h3 className="rec-section-title"><Sparkles size={14} /> AI recommendations</h3>
            )}
            {recommendations.map((recommendation, index) => (
              <article className="rec-card" key={`${recommendation.target_task_id}-${index}`}>
                <h3>{recommendation.type.replaceAll('_', ' ')}</h3>
                <p className="rec-summary">{recommendation.message}</p>
                {recommendation.suggested_subtasks?.length > 0 && (
                  <ul className="rec-steps">
                    {recommendation.suggested_subtasks.map((step, stepIndex) => (
                      <li className="rec-step" key={`${step.title}-${stepIndex}`}>
                        <span className="rec-step-content">
                          <span className="rec-step-label">{step.title}</span>
                          {step.due_date && <span className="rec-step-date">Target: {step.due_date}</span>}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </article>
            ))}
          </>
        )}
      </aside>
    </>
  );
}
