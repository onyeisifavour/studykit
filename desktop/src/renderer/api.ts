import type {
  ArtifactDetail,
  ArtifactSummary,
  BatchEvaluateResult,
  InstanceDetail,
  InstanceSummary,
  MarkPendingResult,
  ChatReply,
  DashboardData,
  DeckDetail,
  DeckSummary,
  EvaluateResult,
  QuizQuestion,
  HistoryDetail,
  LibraryScan,
  QuizGenerateResult,
  QuizJobStatus,
  QuizSummary,
  QuizCompleteResult,
  SettingsData,
} from './types';

let baseUrl: string | null = null;

/**
 * Resolves (and caches) the sidecar base URL.
 *
 * An empty result means the main process could not start the backend. Without
 * this guard the caller's root-relative fetch would resolve against the file://
 * origin the built app runs on and fail with a bare "Failed to fetch", which
 * hides the actual cause (recorded in the sidecar log).
 */
async function apiUrl(): Promise<string> {
  if (!baseUrl) {
    const resolved = await window.studykit.getApiUrl();
    if (!resolved) {
      throw new Error(
        'StudyKit backend failed to start. See ~/.config/studykit-desktop/sidecar.log',
      );
    }
    baseUrl = resolved;
  }
  return baseUrl;
}

/** Resolves (and caches) the sidecar base URL, e.g. for building iframe src. */
export function getBaseUrl(): Promise<string> {
  return apiUrl();
}

/**
 * Returns a *working* sidecar base URL, validating the cached one against
 * /health. If the cached URL is stale (sidecar restarted/exited) we drop it
 * and ask the main process to restart the sidecar and hand back a fresh port.
 * Used before building iframe srcs so dead connections surface immediately.
 */
export async function getLiveBaseUrl(): Promise<string> {
  const cached = baseUrl || (await window.studykit.getApiUrl());
  try {
    const res = await fetch(`${cached}/health`, { cache: 'no-store' });
    if (res.ok) {
      baseUrl = cached;
      return cached;
    }
  } catch {
    // cached URL unreachable — fall through to a fresh resolve
  }
  baseUrl = null;
  const fresh = await window.studykit.getApiUrl(); // main restarts the sidecar
  if (!fresh) throw new Error('Sidecar not available');
  baseUrl = fresh;
  return fresh;
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

async function del<T>(path: string): Promise<T> {
  try {
    const res = await fetch(`${await apiUrl()}${path}`, { method: 'DELETE' });
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
  return get<HistoryDetail>(`/api/history/${encodeURIComponent(quizId)}`);
}

/** Removes one History entry. Only the log is deleted — any stored quiz built
 *  from it stays available to retake. */
export function deleteHistory(quizId: string): Promise<{ deleted: boolean; quiz_id: string }> {
  return del<{ deleted: boolean; quiz_id: string }>(
    `/api/history/${encodeURIComponent(quizId)}`,
  );
}

/** Retake: promotes a completed History entry into an immutable artifact that
 *  can be taken again. The history entry is not modified. */
export function historyToArtifact(quizId: string): Promise<{ artifact_id: string }> {
  return post<{ artifact_id: string }>(
    `/api/history/${encodeURIComponent(quizId)}/to-artifact`,
    {},
  );
}

export function getArtifacts(): Promise<{ artifacts: ArtifactSummary[] }> {
  return get<{ artifacts: ArtifactSummary[] }>('/api/artifacts');
}

export function getArtifact(artifactId: string): Promise<ArtifactDetail> {
  return get<ArtifactDetail>(`/api/artifacts/${encodeURIComponent(artifactId)}`);
}

/** Creates a new independent artifact. `numbers` is the full ordered wish-list
 *  of source question numbers and drives removal, subsetting and reordering;
 *  omit it to duplicate the set unchanged. */
export function deriveArtifact(
  artifactId: string,
  numbers?: number[] | null,
): Promise<{ artifact_id: string; created: boolean }> {
  return post<{ artifact_id: string; created: boolean }>(
    `/api/artifacts/${encodeURIComponent(artifactId)}/derive`,
    { numbers: numbers ?? null, source: 'edit' },
  );
}

export function deleteArtifact(
  artifactId: string,
): Promise<{ deleted: boolean; artifact_id: string }> {
  return del<{ deleted: boolean; artifact_id: string }>(
    `/api/artifacts/${encodeURIComponent(artifactId)}`,
  );
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
  prefs?: {
    section_a_sim: boolean;
    section_a_nonsim: boolean;
    section_b_sim: boolean;
    section_b_nonsim: boolean;
  };
}): Promise<QuizGenerateResult> {
  return post<QuizGenerateResult>('/api/quiz/generate', body);
}

export function quizJobStatus(jobId: string): Promise<QuizJobStatus> {
  return get<QuizJobStatus>(`/api/quiz/job/${jobId}`);
}

export function quizLast(): Promise<QuizJobStatus> {
  return get<QuizJobStatus>('/api/quiz/last');
}

/** Full note for any quiz id — used to reload a saved state's working note. */
export async function getQuizNote(
  quizId: string,
): Promise<{ note: Record<string, unknown> }> {
  return get<{ note: Record<string, unknown> }>(
    `/api/quiz/note/${encodeURIComponent(quizId)}`,
  );
}

/** A working note's questions in quiz-screen card shape, for resuming a state. */
export async function getQuizNoteCards(quizId: string): Promise<{
  quiz_id: string;
  questions: QuizQuestion[];
  topics: string[];
  evaluation_on: boolean | null;
  skip_mode: string | null;
}> {
  return get(`/api/quiz/note/${encodeURIComponent(quizId)}/cards`);
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

export function completeQuiz(body: {
  quiz_id?: string | null;
  answers: {
    number: number;
    user_choice?: string | null;
    choice_meta?: { kind?: string; index?: number } | null;
    skipped?: boolean;
  }[];
  evaluation_on?: boolean;
  skip_mode?: string;
  topics?: string[];
  /** false = "Mark later": leave Hybrid + Theory pending. */
  mark_subjective?: boolean;
  /** Links the finished attempt to the saved state it came from. */
  instance_id?: string | null;
}): Promise<QuizCompleteResult> {
  return post<QuizCompleteResult>('/api/quiz/complete', body);
}

/** Grades a quiz the student deferred with "Mark later", patching its existing
 *  History entry in place. */
export function markPending(quizId: string): Promise<MarkPendingResult> {
  return post<MarkPendingResult>('/api/quiz/mark-pending', { quiz_id: quizId });
}

// ── Instances (mutable attempts) ──────────────────────────────────────────────

export function getInstances(): Promise<{ instances: InstanceSummary[] }> {
  return get<{ instances: InstanceSummary[] }>('/api/instances');
}

export function getInstance(instanceId: string): Promise<InstanceDetail> {
  return get<InstanceDetail>(`/api/instances/${encodeURIComponent(instanceId)}`);
}

/** Begins a new attempt at an artifact. The artifact is only read. */
export function startInstance(artifactId: string): Promise<InstanceDetail> {
  return post<InstanceDetail>(
    `/api/artifacts/${encodeURIComponent(artifactId)}/start`,
    {},
  );
}

/** Pauses the attempt, closing the running stretch as one time entry. */
export function saveInstanceState(
  instanceId: string,
  currentIndex?: number,
): Promise<InstanceDetail> {
  return post<InstanceDetail>(
    `/api/instances/${encodeURIComponent(instanceId)}/save-state`,
    { current_index: currentIndex ?? null },
  );
}

/** Attaches an instance to a working note that already exists, so a
 *  pipeline-generated quiz can be saved without copying its content. */
export function adoptInstance(quizId: string): Promise<InstanceDetail> {
  return post<InstanceDetail>(
    `/api/quiz/${encodeURIComponent(quizId)}/adopt-instance`,
    {},
  );
}

/** First real contact with the quiz: starts the clock. Idempotent. */
export function openInstance(instanceId: string): Promise<InstanceDetail> {
  return post<InstanceDetail>(
    `/api/instances/${encodeURIComponent(instanceId)}/open`,
    {},
  );
}

/** Restarts the clock on a paused attempt, keeping its position. */
export function resumeInstance(instanceId: string): Promise<InstanceDetail> {
  return post<InstanceDetail>(
    `/api/instances/${encodeURIComponent(instanceId)}/resume`,
    {},
  );
}

/** Forks the attempt: a clean slate from the same artifact. */
export function branchInstance(instanceId: string): Promise<InstanceDetail> {
  return post<InstanceDetail>(
    `/api/instances/${encodeURIComponent(instanceId)}/branch`,
    {},
  );
}

export function deleteInstance(
  instanceId: string,
): Promise<{ deleted: boolean; instance_id: string }> {
  return del<{ deleted: boolean; instance_id: string }>(
    `/api/instances/${encodeURIComponent(instanceId)}`,
  );
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
