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
  profile: ScoreProfile;
  results: QuizQuestionResult[];
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
}

export interface HistoryDetail {
  quiz_id: string;
  topic: string;
  subject: string;
  created_at: string;
  skip_mode: string;
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
