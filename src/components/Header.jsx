import { CalendarDays, Camera, Upload } from 'lucide-react';

export default function Header({
  hasDocs,
  onUploadClick,
  onScanClick,
  onToggleSidebar,
}) {
  return (
    <header className="header">
      <div className="header-brand">
        <div className="header-logo" aria-hidden>
          <CalendarDays size={20} strokeWidth={2.25} />
        </div>
        <div className="header-title">
          Sylla<span>Sync</span>
        </div>
      </div>

      <div className="header-actions">
        {hasDocs && (
          <>
            <button
              type="button"
              className="header-btn"
              onClick={onUploadClick}
            >
              <Upload size={15} />
              <span className="header-btn-label">Upload</span>
            </button>
            <button
              type="button"
              className="header-btn header-btn-primary"
              onClick={onScanClick}
            >
              <Camera size={15} />
              <span className="header-btn-label">Scan</span>
            </button>
            <button
              type="button"
              className="header-menu-btn"
              onClick={onToggleSidebar}
              aria-label="Open insights sidebar"
            >
              <CalendarDays size={20} />
            </button>
          </>
        )}
      </div>
    </header>
  );
}
