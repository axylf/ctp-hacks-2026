import { useCallback, useEffect, useRef, useState } from 'react';
import { Camera, Check, Loader2, ScanLine, Trash2, X } from 'lucide-react';

const MAX_PAGES = 10;

/**
 * Camera scanner — captures up to 10 pages and saves them as-is.
 * No invented course / lecture extraction.
 */
export default function ScanSyllabusModal({ onClose, onComplete }) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);

  const [phase, setPhase] = useState('camera'); // camera | saving
  const [pages, setPages] = useState([]);
  const [error, setError] = useState('');
  const [cameraReady, setCameraReady] = useState(false);
  const [flash, setFlash] = useState(false);

  const stopCamera = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function start() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: 'environment' },
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
          setCameraReady(true);
        }
      } catch {
        setError(
          'Could not open the camera. Allow camera permission, or use Upload instead.'
        );
      }
    }

    if (phase === 'camera') start();

    return () => {
      cancelled = true;
      stopCamera();
    };
  }, [phase, stopCamera]);

  const capturePage = () => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || !cameraReady) return;
    if (pages.length >= MAX_PAGES) {
      setError(`Maximum ${MAX_PAGES} pages per scan.`);
      return;
    }

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0);

    setFlash(true);
    setTimeout(() => setFlash(false), 180);

    const dataUrl = canvas.toDataURL('image/jpeg', 0.92);
    setPages((prev) => [
      ...prev,
      { id: `page-${Date.now()}-${prev.length + 1}`, dataUrl },
    ]);
    setError('');
  };

  const savePages = async () => {
    if (pages.length === 0) {
      setError('Capture at least one page before saving.');
      return;
    }

    stopCamera();
    setPhase('saving');

    await new Promise((r) => setTimeout(r, 500));

    const res = await fetch(pages[0].dataUrl);
    const blob = await res.blob();
    const file = new File(
      [blob],
      `scan-${pages.length}-page${pages.length !== 1 ? 's' : ''}.jpg`,
      { type: 'image/jpeg' }
    );

    onComplete(file, {
      source: 'scan',
      pageCount: pages.length,
      pages: pages.map((p) => p.dataUrl),
    });
  };

  const handleClose = () => {
    stopCamera();
    onClose();
  };

  return (
    <div
      className="modal-backdrop scan-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="scan-title"
    >
      <div className="scan-modal">
        <div className="scan-modal-header">
          <div>
            <h2 id="scan-title">
              <ScanLine size={20} style={{ verticalAlign: -4, marginRight: 6 }} />
              Scan pages
            </h2>
            <p>Up to {MAX_PAGES} pages · saved as captured · no invented text</p>
          </div>
          <button
            type="button"
            className="scan-close"
            onClick={handleClose}
            aria-label="Close scanner"
          >
            <X size={18} />
          </button>
        </div>

        {phase === 'camera' && (
          <>
            <div className={`scan-viewport${flash ? ' flash' : ''}`}>
              {error && !cameraReady ? (
                <div className="scan-camera-error">{error}</div>
              ) : (
                <>
                  <video
                    ref={videoRef}
                    className="scan-video"
                    playsInline
                    muted
                    autoPlay
                  />
                  <div className="scan-frame" aria-hidden>
                    <span className="scan-corner tl" />
                    <span className="scan-corner tr" />
                    <span className="scan-corner bl" />
                    <span className="scan-corner br" />
                    <div className="scan-laser" />
                  </div>
                  {!cameraReady && (
                    <div className="scan-loading">
                      <Loader2 className="pipeline-spinner" size={28} />
                      Opening camera…
                    </div>
                  )}
                </>
              )}
            </div>

            <canvas ref={canvasRef} hidden />

            <div className="scan-page-strip">
              {pages.length === 0 ? (
                <p className="scan-page-empty">
                  No pages yet — point the camera and tap Capture.
                </p>
              ) : (
                pages.map((page, idx) => (
                  <div key={page.id} className="scan-thumb">
                    <img src={page.dataUrl} alt={`Page ${idx + 1}`} />
                    <span className="scan-thumb-num">{idx + 1}</span>
                    <button
                      type="button"
                      className="scan-thumb-remove"
                      onClick={() =>
                        setPages((prev) => prev.filter((p) => p.id !== page.id))
                      }
                      aria-label={`Remove page ${idx + 1}`}
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                ))
              )}
            </div>

            {error && cameraReady && (
              <p className="scan-inline-error">{error}</p>
            )}

            <div className="scan-actions">
              <div className="scan-count">
                {pages.length} / {MAX_PAGES} pages
              </div>
              <button
                type="button"
                className="scan-capture-btn"
                onClick={capturePage}
                disabled={!cameraReady || pages.length >= MAX_PAGES}
              >
                <Camera size={18} />
                Capture page
              </button>
              <button
                type="button"
                className="scan-read-btn"
                onClick={savePages}
                disabled={pages.length === 0}
              >
                <Check size={18} />
                Save {pages.length || ''} page{pages.length !== 1 ? 's' : ''}
              </button>
            </div>
          </>
        )}

        {phase === 'saving' && (
          <div className="scan-reading">
            <div className="scan-reading-icon">
              <Loader2 size={36} className="pipeline-spinner" />
            </div>
            <h3>Saving your pages…</h3>
            <p>
              Keeping {pages.length} captured page
              {pages.length !== 1 ? 's' : ''} locally. No course details are being
              invented.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
