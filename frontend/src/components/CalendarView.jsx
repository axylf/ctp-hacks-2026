import { Calendar, Clock3, LayoutGrid, List } from 'lucide-react';

function weekLabel(task) {
  return task.week_label ? `Week ${task.week_label}` : 'Week not listed';
}

function taskCard(task) {
  return <article className="assignment-card" key={task.id}>
    <div className="assignment-card-top"><h3 className="assignment-title">{task.title}</h3><span className="course-badge">{task.course_code}</span></div>
    <div className="assignment-meta"><span className={`type-pill ${task.type}`}>{task.type}</span><span className="assignment-meta-item"><Clock3 size={13} />{weekLabel(task)}</span>{task.needs_review && <span className="assignment-meta-item">Review details</span>}</div>
  </article>;
}

/** Displays only deadlines returned by the backend extraction pipeline. */
export default function CalendarView({ courses, assignments, viewMode, onViewModeChange, selectedCourse, onCourseChange }) {
  const filtered = assignments.filter((task) => selectedCourse === 'all' || task.course_code === selectedCourse).sort((a, b) => (a.week_label || '999').localeCompare(b.week_label || '999', undefined, { numeric: true }));
  const weeks = new Map();
  filtered.filter((task) => task.week_label).forEach((task) => {
    if (!weeks.has(task.week_label)) weeks.set(task.week_label, []);
    weeks.get(task.week_label).push(task);
  });
  const unplanned = filtered.filter((task) => !task.week_label);

  return <div className="calendar-view">
    <div className="calendar-toolbar"><div><h2><Calendar size={20} style={{ verticalAlign: -4, marginRight: 6 }} />Semester Calendar</h2><p className="calendar-toolbar-sub">{filtered.length ? `${filtered.length} extracted deliverable${filtered.length === 1 ? '' : 's'}` : 'Upload a syllabus to extract real deadlines'}</p></div>
      <div className="toolbar-controls"><div className="view-toggle" role="group" aria-label="Calendar view"><button type="button" className={viewMode === 'weekly' ? 'active' : ''} onClick={() => onViewModeChange('weekly')}><LayoutGrid size={14} />Weekly Grid</button><button type="button" className={viewMode === 'timeline' ? 'active' : ''} onClick={() => onViewModeChange('timeline')}><List size={14} />Timeline / List</button></div>
      {courses.length > 0 && <select className="course-filter" value={selectedCourse} onChange={(event) => onCourseChange(event.target.value)} aria-label="Filter by course"><option value="all">View All</option>{courses.map((course) => <option key={course.id} value={course.id}>{course.code} — {course.name}</option>)}</select>}</div>
    </div>
    {filtered.length === 0 ? <div className="empty-calendar"><Calendar size={36} strokeWidth={1.5} /><h3>No deadlines yet</h3><p>Upload or scan a syllabus and the AI will add only the deadlines it finds.</p></div> : viewMode === 'weekly' ? <div className="week-grid">
      {[...weeks.entries()].map(([label, tasks]) => <section key={label} className="week-section"><div className="week-section-header"><h3>Week <span className="week-range">{label}</span></h3><span className="week-count">{tasks.length} item{tasks.length === 1 ? '' : 's'}</span></div><div className="week-cards">{tasks.map(taskCard)}</div></section>)}
      {unplanned.length > 0 && <section className="week-section"><div className="week-section-header"><h3>Week not listed</h3><span className="week-count">{unplanned.length} item{unplanned.length === 1 ? '' : 's'}</span></div><div className="week-cards">{unplanned.map(taskCard)}</div></section>}
    </div> : <div className="timeline">{filtered.map((task) => <div className="timeline-item" key={task.id}><span className="timeline-dot" />{taskCard(task)}</div>)}</div>}
  </div>;
}
