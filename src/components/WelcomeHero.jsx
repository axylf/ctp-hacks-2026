import { useCallback, useRef, useState } from 'react';
import { Camera, FileUp, ScanLine, Sparkles, Upload } from 'lucide-react';

const ACCEPTED = ['application/pdf', 'image/jpeg', 'image/png'];
const ACCEPT_ATTR = '.pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png';

/**
 * Welcome landing — Upload or Scan. Starts with zero course/lecture data.
 */
export default function WelcomeHero({ onFileSelected, onOpenScan }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState('');

  const validateAndSend = useCallback(
    (file) => {
      if (!file) return;
      const okType =
        ACCEPTED.includes(file.type) ||
        /\.(pdf|jpe?g|png)$/i.test(file.name);
      if (!okType) {
        setError('Please upload a PDF or image (JPEG / PNG).');
        return;
      }
      setError('');
      onFileSelected(file);
    },
    [onFileSelected]
  );

  return (
    <section className="welcome">
      <div className="welcome-badge">
        <Sparkles size={14} />
        Your calendar starts empty
      </div>

      <div className="welcome-hero">
        <h1>
          Welcome to <em>Decrunch</em>! Add syllabi as you go.
        </h1>
        <p>
          No more headaches. No more crunching. Burnout goes bye-bye.
        </p>
      </div>

      <div className="intake-grid">
        <div
          className={`intake-card${dragging ? ' is-dragging' : ''}`}
          role="button"
          tabIndex={0}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              inputRef.current?.click();
            }
          }}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            validateAndSend(e.dataTransfer.files?.[0]);
          }}
        >
          <div className="intake-step">1</div>
          <div className="upload-card-icon">
            <Upload size={28} strokeWidth={2} />
          </div>
          <h2>Upload</h2>
          <p>Drag & drop or choose a syllabus file from your device.</p>
          <div className="upload-formats">
            <span className="upload-format">PDF</span>
            <span className="upload-format">JPEG</span>
            <span className="upload-format">PNG</span>
          </div>
          <span className="upload-browse">
            <FileUp size={16} />
            Choose file
          </span>
          <p className="upload-hint">Stored locally in this session only</p>
        </div>

        <div
          className="intake-card scan-card"
          role="button"
          tabIndex={0}
          onClick={onOpenScan}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              onOpenScan();
            }
          }}
        >
          <div className="intake-step">2</div>
          <div className="upload-card-icon scan-card-icon">
            <Camera size={28} strokeWidth={2} />
          </div>
          <h2>Scan a syllabus</h2>
          <p>
            Open your camera and capture up to 10 pages. Pages are saved as-is —
            no invented course details.
          </p>
          <div className="upload-formats">
            <span className="upload-format">Camera</span>
            <span className="upload-format">Up to 10 pages</span>
          </div>
          <span className="upload-browse scan-browse">
            <ScanLine size={16} />
            Open camera & scan
          </span>
          <p className="upload-hint">Ideal for printed / photo pages</p>
        </div>
      </div>

      {error && (
        <p
          className="upload-hint"
          style={{ color: 'var(--crimson-600)', marginTop: '1rem' }}
        >
          {error}
        </p>
      )}

      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT_ATTR}
        hidden
        onChange={(e) => {
          validateAndSend(e.target.files?.[0]);
          e.target.value = '';
        }}
      />
    </section>
  );
}
