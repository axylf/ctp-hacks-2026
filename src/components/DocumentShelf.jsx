import { Camera, FileText, Plus, ScanLine, Trash2, Upload } from 'lucide-react';

function formatBytes(n) {
  if (!n) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Shelf of documents the student has added this session.
 * No course/lecture inventing — just the files/scans they provided.
 */
export default function DocumentShelf({
  documents,
  onRemove,
  onAddUpload,
  onAddScan,
}) {
  return (
    <section className="doc-shelf">
      <div className="doc-shelf-header">
        <div>
          <h2>
            <FileText size={18} style={{ verticalAlign: -3, marginRight: 6 }} />
            Your documents
          </h2>
          <p className="doc-shelf-sub">
            {documents.length} saved · add more anytime · nothing else is invented
          </p>
        </div>
        <div className="doc-shelf-actions">
          <button type="button" className="doc-add-btn" onClick={onAddUpload}>
            <Upload size={15} />
            Upload
          </button>
          <button type="button" className="doc-add-btn doc-add-scan" onClick={onAddScan}>
            <Camera size={15} />
            Scan
          </button>
        </div>
      </div>

      <ul className="doc-list">
        {documents.map((doc) => (
          <li key={doc.id} className="doc-item">
            <div className="doc-thumb">
              {doc.pages?.[0] ? (
                <img src={doc.pages[0]} alt="" />
              ) : (
                <FileText size={22} />
              )}
            </div>
            <div className="doc-meta">
              <div className="doc-name">{doc.name}</div>
              <div className="doc-details">
                <span className="doc-source">
                  {doc.source === 'scan' ? (
                    <>
                      <ScanLine size={12} /> Scanned
                    </>
                  ) : (
                    <>
                      <Upload size={12} /> Uploaded
                    </>
                  )}
                </span>
                <span>
                  {doc.pageCount} page{doc.pageCount !== 1 ? 's' : ''}
                </span>
                {doc.size > 0 && <span>{formatBytes(doc.size)}</span>}
                <span>
                  {new Date(doc.addedAt).toLocaleString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    hour: 'numeric',
                    minute: '2-digit',
                  })}
                </span>
              </div>
            </div>
            <button
              type="button"
              className="doc-remove"
              onClick={() => onRemove(doc.id)}
              aria-label={`Remove ${doc.name}`}
            >
              <Trash2 size={15} />
            </button>
          </li>
        ))}
      </ul>

      <button type="button" className="doc-add-more" onClick={onAddUpload}>
        <Plus size={16} />
        Add another document
      </button>
    </section>
  );
}
