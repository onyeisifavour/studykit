export interface SubjectStat {
  name: string;
  pct: number;
}

export interface WeakTopic {
  topic: string;
  pct: number;
  quiz_ids: string[];
}

export interface RecentQuiz {
  quiz_id: string;
  created_at: string;
  topics: string[];
  completed: boolean;
  mcq: [number, number];
  written_pct: number | null;
  skipped: number;
}

export interface DashboardData {
  quizzes: number;
  questions: number;
  avg_pct: number;
  subjects: SubjectStat[];
  weak_topics: WeakTopic[];
  recent: RecentQuiz[];
  setup_needed: boolean;
}

// ── Quiz ────────────────────────────────────────────────────────────────────

export type QuizQuestionType = 'MCQ' | 'SUBJ' | 'SIM';

export interface QuizQuestion {
  number: number;
  section: string;
  q_type: QuizQuestionType | string;
  is_simulation: boolean;
  question_text: string;
  options: string[];
  correct_answer: string;
  /**
   * Authoritative correct-option position. Options are display text and may
   * reword the correct answer, so text matching is only a fallback for
   * bank-copied and legacy questions. Absent/null on those.
   */
  correct_option_index?: number | null;
  /** Per-option "you likely <mistake>" text, aligned to `options`. Not shown yet. */
  option_rationales?: string[];
  /**
   * Per-option short label for the mistake the option encodes, aligned to
   * `options`; the correct option is 'correct'. The option agent picks these
   * labels itself, so they are free text. Not shown yet.
   */
  option_error_types?: string[];
  sim_name: string;
  sim_instruction: string;
  topic: string;
  pacing_stage?: string;
  objective_type?: string;
}

export interface QuizGenerateResult {
  job_id: string;
  state: string;
}

export interface QuizJobStatus {
  job_id: string;
  state: 'pending' | 'running' | 'done' | 'error' | 'cancelled';
  stage: string;
  detail: string;
  error: string | null;
  ready: boolean;
  questions?: QuizQuestion[];
  topics?: string[];
  quiz_id?: string;
}

export interface QuizFeedback {
  is_correct: boolean;
  score: number | null;
  message: string;
}

export interface QuizReportItem {
  number: number;
  question: string;
  options: string[];
  q_type: string;
  topic: string;
  user_answer: string;
  correct_answer: string;
  is_correct: boolean;
  score: number | null;
  feedback: string;
}

export interface QuizReport {
  topic: string;
  total: number;
  correct: number;
  skipped: number;
  avg_pct: number;
  items: QuizReportItem[];
}

export interface ChatReply {
  reply: string;
}

export interface EvaluateResult {
  score: number;
  feedback: string;
}

export interface BatchEvaluateResult {
  results: { label: string; score: number; explanation: string }[];
}

export interface QuizQuestionResult {
  number: number;
  score: number | null;
  remark: string;
  is_correct: boolean | null;
  skipped?: boolean;
  note?: string;
}

export interface ScoreProfile {
  total: number;
  attempted: number;
  marked: number;
  skipped: number;
  unanswered: number;
  ungraded: number;
  earned: number;
  overall: number | null;
  by_type: Record<string, { earned: number; count: number; correct: number }>;
  by_pacing_stage: Record<string, { earned: number; count: number }>;
  by_topic: Record<string, { earned: number; count: number }>;
}

export interface QuizCompleteResult {
  quiz_id: string;
  history_written: boolean;
  history_quiz_id: string;
  /** True when the student chose "Mark later" — subjective scores are not in
   *  the History entry yet. */
  marking_pending: boolean;
  profile: ScoreProfile;
  results: QuizQuestionResult[];
}

export interface MarkPendingResult {
  quiz_id: string;
  marking_pending: boolean;
  marked: number;
  results: QuizQuestionResult[];
  profile: ScoreProfile;
}

// ── History ──────────────────────────────────────────────────────────────────

export interface QuizSummary {
  quiz_id: string;
  topic: string;
  subject: string;
  created_at: string;
  completed: boolean;
  total: number;
  correct: number;
  skipped: number;
  avg_pct: number;
  skip_mode: string;
  marking_pending: boolean;
}

/** An immutable quiz set. Never carries answers or marks. */
export interface ArtifactSummary {
  artifact_id: string;
  created_at: string;
  source: string;
  topics: string[];
  title: string;
  subject: string;
  total_questions: number;
}

export interface ArtifactQuestion {
  number: number;
  section: string;
  q_type: string;
  question_text: string;
  options: string[];
  correct_answer: string;
  topic: string;
  is_simulation: boolean;
  sim_instruction: string;
}

export interface ArtifactDetail extends ArtifactSummary {
  questions: ArtifactQuestion[];
}

/** One closed stretch of time, appended by every Save State. */
export interface TimeEntry {
  index: number;
  elapsed_secs: number;
  saved_at: string;
}

/** A mutable attempt taken from an artifact. */
export interface InstanceSummary {
  instance_id: string;
  artifact_id: string | null;
  parent_instance_id: string | null;
  title: string;
  subject: string;
  topics: string[];
  created_at: string;
  updated_at: string;
  status: 'created' | 'active' | 'paused' | 'completed';
  total_questions: number;
  answered: number;
  current_index: number;
  /** Number of saved stretches — non-zero means the run was paused. */
  time_entries: number;
  total_secs: number;
  /** null whenever the run was paused, because the mean is then meaningless. */
  avg_secs: number | null;
  was_paused: boolean;
  work_quiz_id: string | null;
  history_quiz_id: string | null;
  marking_pending: boolean;
}

export interface InstanceDetail extends InstanceSummary {
  entries: TimeEntry[];
  answers: { number: number; answered: boolean; skipped: boolean }[];
}

export interface HistoryDetail {
  quiz_id: string;
  topic: string;
  subject: string;
  created_at: string;
  skip_mode: string;
  marking_pending: boolean;
  questions: {
    number: number;
    question: string;
    options: string[];
    section: string;
    q_type: string;
    is_simulation: boolean;
    topic: string;
    user_answer: string;
    correct_answer: string;
    is_correct: boolean | null;
    score: number | null;
    skipped: boolean;
    ai_feedback: string;
  }[];
}

// ── Flashcards ───────────────────────────────────────────────────────────────

export interface DeckSummary {
  id: string;
  title: string;
  subject: string;
  source: 'quiz' | 'library';
  size: number;
}

export interface Flashcard {
  front: string;
  back: string;
  topic: string;
  subject: string;
  q_type: string;
  source: string;
}

export interface DeckDetail extends DeckSummary {
  cards: Flashcard[];
}

// ── Settings ─────────────────────────────────────────────────────────────────

export interface ApiKeysState {
  groq: { keys: string[]; model: string };
  openrouter: { keys: string[]; model: string };
  custom: { url: string; key: string; model: string };
}

export interface SettingsData {
  provider_mode: string;
  cli_model: string;
  api: ApiKeysState;
  library_root: string;
  selected_topics: string[];
  question_types: { mcq: boolean; subj: boolean; sim: boolean };
  sections: {
    section_a_sim: boolean;
    section_a_nonsim: boolean;
    section_b_sim: boolean;
    section_b_nonsim: boolean;
  };
  shuffle: { shuffle_enabled: boolean; keep_sim_together: boolean };
  evaluation_on: boolean;
  last_skip_mode: string;
  question_count: number;
}

// ── Library scan ─────────────────────────────────────────────────────────────

export interface LibraryTopic {
  name: string;
  valid: boolean;
  has_simulations: boolean;
  folder_path: string;
}

export interface LibrarySubject {
  name: string;
  topics: LibraryTopic[];
}

export interface LibraryScan {
  root: string;
  subject_count: number;
  topic_count: number;
  valid_count: number;
  subjects: LibrarySubject[];
}
