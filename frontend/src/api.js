const API_BASE = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '');
const DEMO_USER_EMAIL = import.meta.env.VITE_DEMO_USER_EMAIL || 'alex@example.com';

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, options);
  } catch {
    throw new ApiError('Could not reach the backend. Start it with: uv run python backend/app.py');
  }

  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(body.error || 'The backend could not process that file.', response.status);
  }
  return body;
}

export async function loadPersistedData(userEmail = DEMO_USER_EMAIL) {
  try {
    const body = await request(`/supabase/dashboard?user_email=${encodeURIComponent(userEmail)}`);
    return {
      courses: body.courses || [],
      assignments: body.assignments || [],
      documents: body.documents || [],
      recommendations: body.recommendations || [],
    };
  } catch {
    return { courses: [], assignments: [], documents: [], recommendations: [] };
  }
}

export async function uploadSyllabus(file, meta = {}) {
  const form = new FormData();
  // Syllabi often specify only a week number. Do not let the backend invent a
  // calendar date from a generic term calendar.
  form.append('infer_dates', 'false');

  if (meta.source === 'scan') {
    const pages = meta.pages || [];
    if (pages.length) {
      const blobs = await Promise.all(pages.map(async (page) => (await fetch(page)).blob()));
      blobs.forEach((blob, index) => form.append('images', blob, `scan-page-${index + 1}.jpg`));
    } else {
      form.append('images', file, file.name);
    }
    return request('/syllabus/scan', { method: 'POST', body: form });
  }

  form.append('file', file, file.name);
  return request('/syllabus/upload', { method: 'POST', body: form });
}

export function analyzeTasks(tasks) {
  return request('/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tasks }),
  });
}
