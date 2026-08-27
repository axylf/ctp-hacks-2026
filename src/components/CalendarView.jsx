import { Calendar, LayoutGrid, List } from 'lucide-react';

const WEEK_RANGES = {
  1: 'Sep 22 – Sep 28',
  2: 'Sep 29 – Oct 5',
  3: 'Oct 6 – Oct 12',
  4: 'Oct 13 – Oct 19',
  5: 'Oct 20 – Oct 26',
};

/**
 * Calendar stays empty until real deliverables exist.
 * No hardcoded lectures or assignments.
 */
export default function CalendarView({
  courses,
  assignments,
  viewMode,
  onViewModeChange,
  selectedCourse,
  onCourseChange,
}) {
  const filtered = assignments.filter(
    (a) => selectedCourse === 'all' || a.courseId === selectedCourse
  );

  const weeks = [1, 2, 3, 4, 5];

  return (
    <div className="calendar-view">
      <div className="calendar-toolbar">
        <div>
          <h2>
            <Calendar
              size={20}
              style={{ verticalAlign: -4, marginRight: 6 }}
            />
            Semester Calendar
          </h2>
          <p className="calendar-toolbar-sub">
            {filtered.length === 0
              ? 'Empty for now — deadlines appear only when extracted later'
              : `${filtered.length} deliverable${filtered.length !== 1 ? 's' : ''}`}
          </p>
        </div>

        <div className="toolbar-controls">
          <div className="view-toggle" role="group" aria-label="Calendar view">
            <button
              type="button"
              className={viewMode === 'weekly' ? 'active' : ''}
              onClick={() => onViewModeChange('weekly')}
            >
              <LayoutGrid size={14} />
              Weekly Grid
            </button>
            <button
              type="button"
              className={viewMode === 'timeline' ? 'active' : ''}
              onClick={() => onViewModeChange('timeline')}
            >
              <List size={14} />
              Timeline / List
            </button>
          </div>

          {courses.length > 0 && (
            <select
              className="course-filter"
              value={selectedCourse}
              onChange={(e) => onCourseChange(e.target.value)}
              aria-label="Filter by course"
            >
              <option value="all">View All</option>
              {courses.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code} — {c.name}
                </option>
              ))}
            </select>
          )}
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="empty-calendar">
          <Calendar size={36} strokeWidth={1.5} />
          <h3>No deadlines yet</h3>
          <p>
            Your calendar is blank on purpose. Keep uploading or scanning
            documents as you get them — we will not invent lecture info for you.
          </p>
        </div>
      ) : viewMode === 'weekly' ? (
        <div className="week-grid">
          {weeks.map((week) => {
            const items = filtered.filter((a) => a.week === week);
            return (
              <section key={week} className="week-section">
                <div className="week-section-header">
                  <h3>
                    Week {week}{' '}
                    <span className="week-range">{WEEK_RANGES[week]}</span>
                  </h3>
                  <span className="week-count">
                    {items.length} item{items.length !== 1 ? 's' : ''}
                  </span>
                </div>
                {items.length === 0 ? (
                  <div className="week-empty">No deliverables this week</div>
                ) : null}
              </section>
            );
          })}
        </div>
      ) : (
        <div className="empty-calendar">
          <p>Timeline will fill when deliverables are available.</p>
        </div>
      )}
    </div>
  );
}
