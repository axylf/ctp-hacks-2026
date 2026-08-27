import { Calendar, Clock3, LayoutGrid, List } from 'lucide-react';

function weekStart(value) {
  const date = new Date(`${value}T12:00:00`);
  date.setDate(date.getDate() - date.getDay() + (date.getDay() === 0 ? -6 : 1));
  return date;
}

function dateLabel(value) {
  return value
    ? new Date(`${value}T12:00:00`).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
    : 'Date needs review';
}

function taskCard(task) {
  return <article className="assignment-card" key={task.id}>
    <div className="assignment-card-top"><h3 className="assignment-title">{task.title}</h3><span className="course-badge">{task.course_code}</span></div>
    <div className="assignment-meta"><span className={`type-pill ${task.type}`}>{task.type}</span><span className="assignment-meta-item"><Clock3 size={13} />{dateLabel(task.due_date)}</span>{task.needs_review && <span className="assignment-meta-item">Review date</span>}</div>
  </article>;
}

/** Displays only deadlines returned by the backend extraction pipeline. */
export default function CalendarView({ courses, assignments, viewMode, onViewModeChange, selectedCourse, onCourseChange }) {
  const filtered = assignments.filter((task) => selectedCourse === 'all' || task.course_code === selectedCourse).sort((a, b) => (a.due_date || '9999').localeCompare(b.due_date || '9999'));
  const weeks = new Map();
  filtered.filter((task) => task.due_date).forEach((task) => {
    const start = weekStart(task.due_date);
    const key = start.toISOString().slice(0, 10);
    if (!weeks.has(key)) weeks.set(key, { start, tasks: [] });
    weeks.get(key).tasks.push(task);
  });
  const undated = filtered.filter((task) => !task.due_date);

  return <div className="calendar-view">
    <div className="calendar-toolbar"><div><h2><Calendar size={20} style={{ verticalAlign: -4, marginRight: 6 }} />Semester Calendar</h2><p className="calendar-toolbar-sub">{filtered.length ? `${filtered.length} extracted deliverable${filtered.length === 1 ? '' : 's'}` : 'Upload a syllabus to extract real deadlines'}</p></div>
      <div className="toolbar-controls"><div className="view-toggle" role="group" aria-label="Calendar view"><button type="button" className={viewMode === 'weekly' ? 'active' : ''} onClick={() => onViewModeChange('weekly')}><LayoutGrid size={14} />Weekly Grid</button><button type="button" className={viewMode === 'timeline' ? 'active' : ''} onClick={() => onViewModeChange('timeline')}><List size={14} />Timeline / List</button></div>
      {courses.length > 0 && <select className="course-filter" value={selectedCourse} onChange={(event) => onCourseChange(event.target.value)} aria-label="Filter by course"><option value="all">View All</option>{courses.map((course) => <option key={course.id} value={course.id}>{course.code} — {course.name}</option>)}</select>}</div>
    </div>
    {filtered.length === 0 ? <div className="empty-calendar"><Calendar size={36} strokeWidth={1.5} /><h3>No deadlines yet</h3><p>Upload or scan a syllabus and the AI will add only the deadlines it finds.</p></div> : viewMode === 'weekly' ? <div className="week-grid">
      {[...weeks.values()].map(({ start, tasks }) => <section key={start} className="week-section"><div className="week-section-header"><h3>Week of <span className="week-range">{dateLabel(start.toISOString().slice(0, 10))}</span></h3><span className="week-count">{tasks.length} item{tasks.length === 1 ? '' : 's'}</span></div><div className="week-cards">{tasks.map(taskCard)}</div></section>)}
      {undated.length > 0 && <section className="week-section"><div className="week-section-header"><h3>Needs date review</h3><span className="week-count">{undated.length} item{undated.length === 1 ? '' : 's'}</span></div><div className="week-cards">{undated.map(taskCard)}</div></section>}
    </div> : <div className="timeline">{filtered.map((task) => <div className="timeline-item" key={task.id}><span className="timeline-dot" />{taskCard(task)}</div>)}</div>}
  </div>;
}
