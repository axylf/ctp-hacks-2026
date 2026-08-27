import { useCallback, useRef, useState } from 'react';
import Header from './components/Header';
import WelcomeHero from './components/WelcomeHero';
import UploadModal from './components/UploadModal';
import ScanSyllabusModal from './components/ScanSyllabusModal';
import CalendarView from './components/CalendarView';
import OverloadSidebar from './components/OverloadSidebar';
import DocumentShelf from './components/DocumentShelf';
import { analyzeTasks, uploadSyllabus } from './api';

/**
 * Decrunch — local-only. Starts empty; only stores what you upload or scan.
 * No hardcoded courses, lectures, or deadlines.
 */
export default function App() {
  const [documents, setDocuments] = useState([]);
  const [courses, setCourses] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [recommendations, setRecommendations] = useState([]);
  const [selectedCourse, setSelectedCourse] = useState('all');
  const [apiError, setApiError] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [scanOpen, setScanOpen] = useState(false);
  const [fileName, setFileName] = useState('');
  const [processMode, setProcessMode] = useState('upload');
  const [pageCount, setPageCount] = useState(null);
  const [viewMode, setViewMode] = useState('weekly');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const reuploadRef = useRef(null);
  const pendingRef = useRef(null);
  const pendingMetaRef = useRef(null);

  const addDocument = useCallback((file, meta, result) => {
    setDocuments((prev) => [
      {
        id: `doc-${Date.now()}`,
        name: file.name,
        source: meta?.source === 'scan' ? 'scan' : 'upload',
        pageCount: meta?.pageCount || 1,
        pages: meta?.pages || [],
        mimeType: file.type || 'application/octet-stream',
        size: file.size || 0,
        addedAt: new Date().toISOString(),
        taskIds: result.tasks.map((task) => task.id),
      },
      ...prev,
    ]);
  }, []);

  const removeDocument = useCallback((id) => {
    setDocuments((prev) => {
      const removed = prev.find((document) => document.id === id);
      if (removed) {
        setAssignments((tasks) => tasks.filter((task) => !removed.taskIds.includes(task.id)));
      }
      return prev.filter((document) => document.id !== id);
    });
  }, []);

  const startProcessing = useCallback((file, meta = null) => {
    setFileName(file.name);
    setProcessMode(meta?.source === 'scan' ? 'scan' : 'upload');
    setPageCount(meta?.pageCount ?? null);
    pendingRef.current = file;
    pendingMetaRef.current = meta;
    setIsProcessing(true);
  }, []);

  const handleFileSelected = useCallback(
    (file) => startProcessing(file, { source: 'upload' }),
    [startProcessing]
  );

  const handleScanComplete = useCallback(
    (file, meta) => {
      setScanOpen(false);
      startProcessing(file, meta);
    },
    [startProcessing]
  );

  const handleProcessComplete = useCallback(async () => {
    const file = pendingRef.current;
    const meta = pendingMetaRef.current;
    if (!file) return;

    try {
      setApiError('');
      const result = await uploadSyllabus(file, meta || {});
      const course = {
        id: result.course.code,
        code: result.course.code || 'Course',
        name: result.course.name || 'Untitled course',
      };
      setCourses((current) =>
        current.some((item) => item.id === course.id) ? current : [...current, course]
      );

      const combinedTasks = [
        ...assignments.filter((task) => !result.tasks.some((next) => next.id === task.id)),
        ...result.tasks,
      ];
      const analysis = await analyzeTasks(combinedTasks);
      setAssignments(analysis.tasks);
      setRecommendations(analysis.recommendations);
      addDocument(file, meta, result);
      pendingRef.current = null;
      pendingMetaRef.current = null;
    } catch (error) {
      setApiError(error.message || 'Could not process that file.');
    } finally {
      setIsProcessing(false);
    }
  }, [addDocument, assignments]);

  const onReuploadChange = (e) => {
    const file = e.target.files?.[0];
    if (file) handleFileSelected(file);
    e.target.value = '';
  };

  const hasDocs = documents.length > 0;

  return (
    <div className="app">
      <Header
        hasDocs={hasDocs}
        onUploadClick={() => reuploadRef.current?.click()}
        onScanClick={() => setScanOpen(true)}
        onToggleSidebar={() => setSidebarOpen((o) => !o)}
      />

      <main className="app-main">
        {!hasDocs ? (
          <WelcomeHero
            onFileSelected={handleFileSelected}
            onOpenScan={() => setScanOpen(true)}
          />
        ) : (
          <div className="app-dashboard">
            <div className="app-dashboard-main">
              <DocumentShelf
                documents={documents}
                onRemove={removeDocument}
                onAddUpload={() => reuploadRef.current?.click()}
                onAddScan={() => setScanOpen(true)}
              />
              <CalendarView
                courses={courses}
                assignments={assignments}
                viewMode={viewMode}
                onViewModeChange={setViewMode}
                selectedCourse={selectedCourse}
                onCourseChange={setSelectedCourse}
              />
              {apiError && <p className="api-error" role="alert">{apiError}</p>}
            </div>
            <OverloadSidebar
              open={sidebarOpen}
              onClose={() => setSidebarOpen(false)}
              recommendations={recommendations}
              assignments={assignments}
            />
          </div>
        )}
      </main>

      {scanOpen && (
        <ScanSyllabusModal
          onClose={() => setScanOpen(false)}
          onComplete={handleScanComplete}
        />
      )}

      {isProcessing && (
        <UploadModal
          fileName={fileName}
          mode={processMode}
          pageCount={pageCount}
          onComplete={handleProcessComplete}
        />
      )}

      <input
        ref={reuploadRef}
        type="file"
        accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
        hidden
        onChange={onReuploadChange}
      />
    </div>
  );
}
