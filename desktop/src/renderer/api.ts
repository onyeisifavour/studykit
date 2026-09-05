import type {
  BatchEvaluateResult,
  ChatReply,
  DashboardData,
  DeckDetail,
  DeckSummary,
  EvaluateResult,
  HistoryDetail,
  LibraryScan,
  QuizGenerateResult,
  QuizJobStatus,
  QuizSummary,
  SettingsData,
} from './types';

let baseUrl: string | null = null;

async function apiUrl(): Promise<string> {
  if (!baseUrl) baseUrl = await window.studykit.getApiUrl();
  return baseUrl;
}

function clearOnNetworkError(e: unknown): unknown {
  // "Failed to fetch" (TypeError) means the sidecar connection is dead —
  // forget the cached URL so the next call re-resolves and restarts it.
  if (e instanceof TypeError) baseUrl = null;
  return e;
}

async function get<T>(path: string): Promise<T> {
  try {
    const res = await fetch(`${await apiUrl()}${path}`);
    if (!res.ok) {
      throw new Error(`${path} failed with status ${res.status}`);
    }
    return (await res.json()) as T;
  } catch (e) {
    throw clearOnNetworkError(e);
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  try {
    const res = await fetch(`${await apiUrl()}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      throw new Error(`${path} failed with status ${res.status}`);
    }
    return (await res.json()) as T;
  } catch (e) {
    throw clearOnNetworkError(e);
  }
}

export function getDashboard(): Promise<DashboardData> {
  return get<DashboardData>('/api/dashboard');
}

export function getHistory(): Promise<{ quizzes: QuizSummary[] }> {
  return get<{ quizzes: QuizSummary[] }>('/api/history');
}

export function getHistoryDetail(quizId: string): Promise<HistoryDetail> {
  return get<HistoryDetail>(`/api/history/${quizId}`);
}

export function getDecks(): Promise<{ quiz_decks: DeckSummary[]; library_decks: DeckSummary[] }> {
  return get<{ quiz_decks: DeckSummary[]; library_decks: DeckSummary[] }>(
    '/api/flashcards/decks',
  );
}

export function getDeck(deckId: string): Promise<{ deck: DeckDetail }> {
  return get<{ deck: DeckDetail }>(`/api/flashcards/deck/${encodeURIComponent(deckId)}`);
}

export function getSettings(): Promise<SettingsData> {
  return get<SettingsData>('/api/settings');
}

export function saveSettings(body: Partial<SettingsData>): Promise<SettingsData> {
  return post<SettingsData>('/api/settings', body);
}

export function scanLibrary(root: string): Promise<LibraryScan> {
  return post<LibraryScan>('/api/library/scan', { root });
}

export async function getUser(): Promise<{ name: string }> {
  return window.studykit.getUser();
}

// ── Quiz generation / chat / evaluation ────────────────────────────────────

export function quizChat(body: {
  message: string;
  history: { role: string; content: string }[];
}): Promise<ChatReply> {
  return post<ChatReply>('/api/quiz/chat', body);
}

export function quizGenerate(body: {
  user_request: string;
  history?: { role: string; content: string }[];
  question_count?: number;
}): Promise<QuizGenerateResult> {
  return post<QuizGenerateResult>('/api/quiz/generate', body);
}

export function quizJobStatus(jobId: string): Promise<QuizJobStatus> {
  return get<QuizJobStatus>(`/api/quiz/job/${jobId}`);
}

export async function quizCancel(jobId: string): Promise<QuizJobStatus> {
  try {
    const res = await fetch(`${await apiUrl()}/api/quiz/job/${jobId}/cancel`, { method: 'POST' });
    if (!res.ok) throw new Error(`quiz cancel failed with status ${res.status}`);
    return (await res.json()) as QuizJobStatus;
  } catch (e) {
    throw clearOnNetworkError(e);
  }
}

export function quizEvaluate(body: {
  question: string;
  user_answer: string;
  correct_answer: string;
}): Promise<EvaluateResult> {
  return post<EvaluateResult>('/api/quiz/evaluate', body);
}

export function quizBatchEvaluate(body: {
  question_groups: {
    number: string;
    subquestions: { label: string; question: string; user_answer: string; correct_answer: string }[];
  }[];
}): Promise<BatchEvaluateResult> {
  return post<BatchEvaluateResult>('/api/quiz/evaluate-batch', body);
}

export function tutorChat(body: {
  question: string;
  user_answer: string;
  correct_answer: string;
  follow_up: string;
  options?: string[];
  history: { role: string; content: string }[];
}): Promise<{ reply: string }> {
  return post<{ reply: string }>('/api/tutor/chat', body);
}
