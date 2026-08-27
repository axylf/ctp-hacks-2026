import { useEffect, useRef, useState } from 'react';
import { Check, FileText, Loader2 } from 'lucide-react';

const STEP_MS = 700;

const UPLOAD_STEPS = [
  { id: 1, label: 'Saving your file to this session…', team: 'SyllaSync' },
  { id: 2, label: 'Done. Document added — nothing else invented.', team: 'SyllaSync' },
];

const SCAN_STEPS = [
  { id: 1, label: 'Saving captured pages to this session…', team: 'SyllaSync' },
  { id: 2, label: 'Done. Pages stored as-is — no invented lecture data.', team: 'SyllaSync' },
];

/** Short local save overlay — no fake CV/Gemini lecture extraction. */
export default function UploadModal({
  fileName,
  onComplete,
  mode = 'upload',
  pageCount,
}) {
  const steps = mode === 'scan' ? SCAN_STEPS : UPLOAD_STEPS;
  const [currentStep, setCurrentStep] = useState(0);
  const onCompleteRef = useRef(onComplete);
  const finishedRef = useRef(false);

  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);

  useEffect(() => {
    finishedRef.current = false;
    const timers = [];
    const active = mode === 'scan' ? SCAN_STEPS : UPLOAD_STEPS;

    active.forEach((_, index) => {
      timers.push(
        setTimeout(() => setCurrentStep(index + 1), STEP_MS * (index + 1))
      );
    });

    timers.push(
      setTimeout(() => {
        if (!finishedRef.current) {
          finishedRef.current = true;
          onCompleteRef.current();
        }
      }, STEP_MS * active.length + 300)
    );

    return () => timers.forEach(clearTimeout);
  }, [mode]);

  const displayStep = Math.min(currentStep, steps.length);
  const progress = Math.min(
    100,
    Math.round((displayStep / steps.length) * 100)
  );

  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="process-title"
    >
      <div className="modal">
        <div className="modal-header">
          <h2 id="process-title">
            {mode === 'scan' ? 'Saving scan' : 'Saving upload'}
          </h2>
          <p>Local session only — no hardcoded courses or deadlines.</p>
          {fileName && (
            <div className="modal-filename">
              <FileText size={14} />
              {fileName}
              {mode === 'scan' && pageCount
                ? ` · ${pageCount} page${pageCount !== 1 ? 's' : ''}`
                : ''}
            </div>
          )}
        </div>

        <div className="pipeline">
          {steps.map((step, index) => {
            const done = displayStep > index;
            const active = displayStep === index;
            return (
              <div
                key={step.id}
                className={`pipeline-step${done ? ' done' : ''}${active ? ' active' : ''}`}
              >
                <div className="pipeline-icon">
                  {done ? (
                    <Check size={16} strokeWidth={2.5} />
                  ) : active ? (
                    <Loader2 size={16} className="pipeline-spinner" />
                  ) : (
                    <span style={{ fontSize: 12, fontWeight: 700 }}>
                      {step.id}
                    </span>
                  )}
                </div>
                <div className="pipeline-body">
                  <div className="pipeline-team">{step.team}</div>
                  <div className="pipeline-label">{step.label}</div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="progress-bar" aria-hidden>
          <div className="progress-bar-fill" style={{ width: `${progress}%` }} />
        </div>
      </div>
    </div>
  );
}
