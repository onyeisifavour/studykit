import { useEffect, useReducer, useRef } from 'react';
import { ChatBubbles, ChatInput } from '../components/ChatComposer';
import { quizChat, quizGenerate, quizJobStatus, quizCancel, quizEvaluate, quizBatchEvaluate } from '../api';
import type { QuizQuestion } from '../types';

interface Props {
  onNavigate: (screen: string) => void;
  active: boolean;
}

// ── Mock data (ported verbatim from electron_UI_prototype.html) ──────────────

interface MockQ {
  type: 'MCQ' | 'Written';
  isSim: boolean;
  sec: string;
  text: string;
  opts?: string[];
  correct?: number;
  simInstr?: string;
  pacing: string;
}

// Display model derived from real backend questions (see toMockQs below).
function toMockQs(real: QuizQuestion[]): MockQ[] {
  return real.map((r) => {
    const isSim = !!r.is_simulation;
    const disptype: MockQ['type'] = r.q_type === 'MCQ' ? 'MCQ' : 'Written';
    const correct = r.options.findIndex((o) => o.trim().toUpperCase().startsWith((r.correct_answer || '').trim().toUpperCase().slice(0, 1)));
    return {
      type: disptype,
      isSim,
      sec: r.section || (r.q_type === 'MCQ' ? 'A' : 'B'),
      text: r.question_text,
      opts: r.options && r.options.length ? r.options : undefined,
      correct: correct >= 0 ? correct : undefined,
      simInstr: r.sim_instruction || undefined,
      pacing: r.pacing_stage || r.objective_type || '—',
    };
  });
}

const P_MSGS = [
  { main: 'Planning your quiz…', sub: 'Analysing topics and your conversation', lbl: 'Stage 1 of 4' },
  { main: 'Finding your questions…', sub: "Searching banks for your selected topics", lbl: 'Stage 2 of 4' },
  { main: 'Ordering your questions…', sub: 'Sequencing for pacing and diagnostic flow', lbl: 'Stage 3 of 4' },
  { main: 'Running final checks…', sub: 'Auditing structure, coverage, and answer formats', lbl: 'Stage 4 of 4' },
];

const P_DETAIL = [
  'Parsing chat history and generating a quiz blueprint…',
  'Scoring and filtering candidate questions from your banks…',
  'Applying pacing model: Warm-up → Repair → Core → Transfer…',
  'Checking question types, count, and compliance constraints…',
];

const P_BADGE = ['PLANNING', 'FINDING', 'ORDERING', 'AUDITING'];

type Fb = { type: string; ok: boolean | null; txt: string | null; score: number | null; skipped: boolean };

interface Ans {
  sel: number | null;
  written: string;
  submitted: boolean;
  skipped: boolean;
  fb: Fb | null;
  timeSpent: number;
  timeCommitted: boolean;
}

interface QSet {
  evalOn: boolean;
  autoNext: boolean;
  timerMode: 'off' | 'perQ' | 'total';
  timerPerQ: number;
  timerTotal: number;
  totalExpiry: 'end' | 'continue';
}

interface Timer {
  mode: string;
  budget: number;
  rem: number;
  totalRem: number;
  totalInit: boolean;
  expired: boolean;
  qSecs: number;
  elapsed: number;
  running: boolean;
  wasRunning: boolean;
  last: number;
}

interface ChatMsg {
  r: 'ai' | 'user';
  t?: string;
  typing?: boolean;
}

const DEF_QSET: QSet = { evalOn: true, autoNext: false, timerMode: 'off', timerPerQ: 60, timerTotal: 10, totalExpiry: 'end' };

function fmtT(s: number): string {
  s = Math.max(0, Math.round(s));
  return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
}

function newAns(): Ans {
  return { sel: null, written: '', submitted: false, skipped: false, fb: null, timeSpent: 0, timeCommitted: false };
}

export default function Quiz({ onNavigate, active }: Props) {
  const [, bump] = useReducer((x: number) => x + 1, 0);

  const Q = useRef({
    state: 'chat' as 'chat' | 'pipeline' | 'peek' | 'cancelled' | 'active' | 'report',
    chatStarted: false,
    chatMsgs: [{ r: 'ai', t: "Hi Favour! I'll help you design a personalised quiz. Which subjects or topics would you like to focus on today?" }] as ChatMsg[],
    chatHistory: [] as { role: string; content: string }[],
    realQs: [] as QuizQuestion[],
    topics: [] as string[],
    jobId: null as string | null,
    pollTimer: null as ReturnType<typeof setInterval> | null,
    pStep: 0,
    qset: DEF_QSET as QSet,
    cur: 0,
    ans: [] as Ans[],
    skipMode: 0,
    qspCollapsed: false,
    qmapOpen: false,
    fbCollapsed: false,
    errVisible: false,
    errText: 'Please select an option, or use Skip.',
    timer: { mode: 'off', budget: 0, rem: 0, totalRem: 0, totalInit: false, expired: false, qSecs: 0, elapsed: 0, running: false, wasRunning: false, last: 0 } as Timer,
    iv: null as ReturnType<typeof setInterval> | null,
    pTimer: null as ReturnType<typeof setTimeout> | null,
    pSubTimer: null as ReturnType<typeof setInterval> | null,
    sub: 0,
    sendBusy: false,
    genError: null as string | null,
  });

  const q = () => Q.current;

  const allQs = () => toMockQs(q().realQs);
  const totalQs = () => q().realQs.length;
  const curQ = () => toMockQs(q().realQs)[q().cur];
  const stopPoll = () => {
    if (q().pollTimer) { clearInterval(q().pollTimer ?? undefined); q().pollTimer = null; }
  };

  // ── Timer engine ────────────────────────────────────────────────────────────

  const stopTimer = () => {
    const t = q().timer;
    if (q().iv) clearInterval(q().iv ?? undefined);
    q().iv = null;
    t.running = false;
    t.wasRunning = false;
  };

  const tick = () => {
    const t = q().timer;
    if (!t.running) return;
    const now = Date.now();
    const dt = Math.floor((now - (t.last || now)) / 1000);
    if (dt <= 0) return;
    t.last = now;
    t.elapsed += dt;
    t.qSecs += dt;
    const mode = q().qset.timerMode;
    if (mode === 'off') {
      bump();
      return;
    }
    if (mode === 'total') t.totalRem -= dt;
    t.rem = Math.max(0, t.rem - dt);
    bump();
    if (mode === 'total' && t.totalRem <= 0) {
      overallTimeUp();
      return;
    }
    if (t.rem <= 0 && !t.expired) timeUp();
  };

  const startQuizClock = () => {
    stopTimer();
    const t = q().timer;
    const qs = q().qset;
    t.qSecs = 0;
    t.mode = qs.timerMode;
    if (qs.timerMode === 'perQ') t.budget = qs.timerPerQ;
    else if (qs.timerMode === 'total') {
      if (!t.totalInit) {
        t.totalRem = qs.timerTotal * 60;
        t.totalInit = true;
      }
      t.budget = t.totalRem > 0 ? Math.max(1, Math.ceil(t.totalRem / Math.max(1, totalQs() - q().cur))) : 0;
    } else t.budget = 0;
    t.rem = t.budget;
    t.last = Date.now();
    t.running = true;
    t.wasRunning = false;
    q().iv = setInterval(tick, 250);
    bump();
  };

  const pauseTimer = () => {
    const t = q().timer;
    if (t.running && q().iv) {
      clearInterval(q().iv ?? undefined);
      q().iv = null;
      t.running = false;
      t.wasRunning = true;
    }
  };

  const resumeTimer = () => {
    const t = q().timer;
    if (!t.wasRunning) return;
    t.wasRunning = false;
    t.last = Date.now();
    t.running = true;
    q().iv = setInterval(tick, 250);
    bump();
  };

  const commitQTime = (i: number) => {
    const a = q().ans[i];
    if (a && !a.timeCommitted) {
      a.timeSpent += q().timer.qSecs;
      a.timeCommitted = true;
      q().timer.qSecs = 0;
    }
  };

  const timeUp = () => {
    stopTimer();
    const a = q().ans[q().cur];
    if (!a) return;
    commitQTime(q().cur);
    const qs = q().qset;
    if (qs.evalOn) {
      a.submitted = true;
      a.skipped = true;
      a.fb = { type: 'time', ok: null, txt: 'Time ran out for this question. It has been marked as skipped.', score: null, skipped: true };
      bump();
    } else {
      nextQ();
    }
  };

  const overallTimeUp = () => {
    const t = q().timer;
    if (t.expired) return;
    t.expired = true;
    stopTimer();
    if (q().qset.totalExpiry === 'end') endQuiz();
    else timeUp();
  };

  // Pause/resume when leaving/entering the screen while a quiz is active.
  useEffect(() => {
    if (!active) {
      pauseTimer();
    } else if (q().state === 'active') {
      resumeTimer();
    }
  }, [active]);

  // ── Chat ────────────────────────────────────────────────────────────────────

  const startChat = () => {
    q().chatStarted = true;
    bump();
  };

  const sendMsg = (text: string) => {
    const c = q().chatMsgs;
    c.push({ r: 'user', t: text });
    c.push({ r: 'ai', typing: true });
    q().chatHistory.push({ role: 'user', content: text });
    q().sendBusy = true;
    bump();
    quizChat({ message: text, history: q().chatHistory.slice(0, -1) })
      .then((res) => {
        c[c.length - 1] = { r: 'ai', t: res.reply };
        q().chatHistory.push({ role: 'assistant', content: res.reply });
        q().sendBusy = false;
        bump();
      })
      .catch((err) => {
        c[c.length - 1] = { r: 'ai', t: 'Sorry, I hit an error reaching the AI chat: ' + ((err && err.message) || err) };
        q().sendBusy = false;
        bump();
      });
  };

  // ── Pipeline ────────────────────────────────────────────────────────────────

  const STAGE_INDEX: Record<string, number> = { planning: 0, finding: 1, ordering: 2, auditing: 3 };

  const pollJob = () => {
    const jobId = q().jobId;
    if (!jobId) return;
    quizJobStatus(jobId)
      .then((st) => {
        if (q().state === 'cancelled' || q().state === 'report') { stopPoll(); return; }
        q().pStep = STAGE_INDEX[st.stage] ?? 0;
        bump();
        if (st.state === 'done' && st.questions) {
          stopPoll();
          q().realQs = st.questions;
          q().topics = st.topics || [];
          loadQuiz();
        } else if (st.state === 'error') {
          stopPoll();
          q().genError = st.error || 'Quiz generation failed.';
          q().state = 'cancelled';
          bump();
        } else if (st.state === 'cancelled') {
          stopPoll();
          q().state = 'cancelled';
          bump();
        }
      })
      .catch(() => {
        // transient network error — keep polling
      });
  };

  const beginPipeline = () => {
    q().pStep = 0;
    q().genError = null;
    stopPoll();
    q().state = 'pipeline';
    bump();
    const userRequest =
      q().chatHistory.filter((m) => m.role === 'user').map((m) => m.content).join(' ') ||
      'Generate a quiz';
    quizGenerate({ user_request: userRequest, history: q().chatHistory.slice() })
      .then((res) => {
        q().jobId = res.job_id;
        bump();
        pollJob();
        q().pollTimer = setInterval(() => pollJob(), 1500);
      })
      .catch((err) => {
        q().genError = (err && err.message) || 'Failed to start quiz generation.';
        q().state = 'cancelled';
        bump();
      });
  };

  const doPeek = () => {
    if (q().pTimer) clearTimeout(q().pTimer ?? undefined);
    if (q().pSubTimer) clearInterval(q().pSubTimer ?? undefined);
    q().state = 'peek';
    bump();
  };

  const resumePipeline = () => {
    q().state = 'pipeline';
    bump();
  };

  const doCancel = () => {
    const jobId = q().jobId;
    if (jobId) quizCancel(jobId).catch(() => {});
    stopPoll();
    if (q().pTimer) clearTimeout(q().pTimer ?? undefined);
    if (q().pSubTimer) clearInterval(q().pSubTimer ?? undefined);
    q().state = 'cancelled';
    bump();
  };

  const doRetry = () => {
    beginPipeline();
  };

  useEffect(() => {
    return () => {
      stopPoll();
      if (q().pTimer) clearTimeout(q().pTimer ?? undefined);
      if (q().pSubTimer) clearInterval(q().pSubTimer ?? undefined);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Active quiz ─────────────────────────────────────────────────────────────

  const loadQuiz = () => {
    q().cur = 0;
    const t = q().timer;
    t.elapsed = 0;
    t.totalRem = 0;
    t.totalInit = false;
    t.expired = false;
    q().ans = q().realQs.map(() => newAns());
    q().state = 'active';
    bump();
    requestAnimationFrame(() => startQuizClock());
  };

  const selectOpt = (i: number) => {
    const a = q().ans[q().cur];
    if (q().qset.evalOn && a.submitted) return;
    a.sel = i;
    bump();
  };

  const saveWritten = (v: string) => {
    q().ans[q().cur].written = v;
  };

  const submitAns = () => {
    const i = q().cur;
    const qd = curQ();
    const a = q().ans[i];
    const isOpt = qd.type === 'MCQ' && qd.opts && qd.opts.length;
    if (isOpt && a.sel === null) {
      q().errText = 'Please select an option, or use Skip.';
      q().errVisible = true;
      bump();
      return;
    }
    if (qd.type === 'Written' && !a.written.trim()) {
      q().errText = 'Please write an answer, or use Skip.';
      q().errVisible = true;
      bump();
      return;
    }
    q().errVisible = false;
    commitQTime(i);
    a.submitted = true;
    if (!q().qset.evalOn) {
      if (q().qset.autoNext) nextQ();
      else bump();
      return;
    }
    if (qd.type === 'Written') {
      a.fb = { type: 'loading', ok: null, txt: null, score: null, skipped: false };
      bump();
      const real = q().realQs[i];
      quizEvaluate({
        question: real.question_text,
        user_answer: a.written,
        correct_answer: real.correct_answer,
      })
        .then((r) => {
          a.fb = { type: 'score', ok: null, txt: r.feedback, score: r.score, skipped: false };
          bump();
        })
        .catch((err) => {
          a.fb = { type: 'score', ok: null, txt: 'Evaluation failed: ' + ((err && err.message) || err), score: null, skipped: false };
          bump();
        });
    } else {
      const ok = a.sel === qd.correct;
      a.fb = { type: ok ? 'correct' : 'wrong', ok, txt: ok ? 'Correct! Well done.' : 'Not quite — the correct answer is ' + (qd.opts ? qd.opts[qd.correct ?? 0] : '') + '.', score: null, skipped: false };
      bump();
    }
  };

  const skipQ = () => {
    const i = q().cur;
    const a = q().ans[i];
    commitQTime(i);
    if (!q().qset.evalOn) {
      if (q().qset.autoNext) nextQ();
      else bump();
      return;
    }
    a.submitted = true;
    a.skipped = true;
    a.fb = { type: 'neutral', ok: null, txt: null, score: null, skipped: true };
    bump();
  };

  const prevQ = () => {
    commitQTime(q().cur);
    if (q().cur > 0) {
      q().cur--;
      bump();
      requestAnimationFrame(() => startQuizClock());
    }
  };

  const nextQ = () => {
    commitQTime(q().cur);
    if (q().cur < totalQs() - 1) {
      q().cur++;
      bump();
      requestAnimationFrame(() => startQuizClock());
    } else {
      endQuiz();
    }
  };

  const gotoQ = (i: number) => {
    commitQTime(q().cur);
    q().cur = i;
    q().qmapOpen = false;
    bump();
    requestAnimationFrame(() => startQuizClock());
  };

  const endQuiz = () => {
    if (q().pTimer) clearTimeout(q().pTimer ?? undefined);
    if (q().pSubTimer) clearInterval(q().pSubTimer ?? undefined);
    commitQTime(q().cur);
    stopTimer();
    q().state = 'report';
    bump();
  };

  const newQuiz = () => {
    stopTimer();
    stopPoll();
    const t = q().timer;
    t.elapsed = 0;
    t.totalRem = 0;
    t.totalInit = false;
    t.expired = false;
    q().chatMsgs = [{ r: 'ai', t: "Hi Favour! I'll help you design a personalised quiz. Which subjects or topics would you like to focus on today?" }];
    q().chatHistory = [];
    q().realQs = [];
    q().topics = [];
    q().jobId = null;
    q().genError = null;
    q().chatStarted = false;
    q().state = 'chat';
    q().ans = [];
    q().cur = 0;
    bump();
  };

  // ── QSP / settings helpers ──────────────────────────────────────────────────

  const setQset = (patch: Partial<QSet>) => {
    q().qset = { ...q().qset, ...patch };
    bump();
  };

  // ── Derived render data ─────────────────────────────────────────────────────

  const state = q().state;
  const qset = q().qset;
  const timer = q().timer;
  const cur = q().cur;
  const qd = curQ();
  const a = q().ans[cur] ?? newAns();
  const total = totalQs();
  const n = cur + 1;
  const msgs = q().chatMsgs;
  const pMsg = P_MSGS[Math.min(q().pStep, 3)];

  const showQSP = state !== 'active';

  // report stats
  const qsAll = allQs();
  const objective = qsAll.filter((x) => x.type === 'MCQ');
  const written = qsAll.filter((x) => x.type === 'Written');
  const report = (() => {
    const ok = objective.reduce((s, _, i) => {
      const qi = qsAll.indexOf(objective[i]);
      const an = q().ans[qi];
      return s + (an.skipped ? 0 : an.sel === objective[i].correct ? 1 : 0);
    }, 0);
    const wScores = written
      .map((_, i) => {
        const an = q().ans[qsAll.indexOf(written[i])];
        return an.fb && an.fb.score != null ? an.fb.score : null;
      })
      .filter((x): x is number => x !== null);
    const wPct = wScores.length ? Math.round((wScores.reduce((s, x) => s + x, 0) / wScores.length) * 100) : null;
    const skipped = q().ans.filter((an) => an.skipped).length;
    return { ok, tot: objective.length, wPct, skipped };
  })();

  const evalHint = qset.evalOn
    ? 'Live: answers are marked and feedback shown after each question.'
    : 'End of quiz: nothing is marked until you finish — you can reanswer any question.';
  const autoHint = qset.evalOn
    ? 'Auto next applies when evaluation is off. Turn evaluation off to use it.'
    : 'Jump to the next question automatically after answering.';
  const perQsecs = Math.max(1, Math.ceil((qset.timerTotal * 60) / Math.max(1, total)));
  const timerHint = qset.timerMode === 'off'
    ? 'No time limit. Time per question is still recorded.'
    : qset.timerMode === 'perQ'
      ? `${qset.timerPerQ}s per question. Time out → advance.`
      : `Total ${qset.timerTotal} min → ≈${fmtT(perQsecs)}/q. ${qset.totalExpiry === 'end' ? 'Ends quiz at 0.' : 'Recorded only.'}`;
  const reportTime = qset.timerMode === 'off' ? '—' : qset.timerMode === 'total' ? `${fmtT(timer.elapsed)} / ${fmtT(qset.timerTotal * 60)}` : fmtT(timer.elapsed);

  return (
    <section className={active ? 'screen active' : 'screen'} id="screen-quiz">
      <div className="quiz-workspace">
      <div className="quiz-main">
        {/* STATE: CHAT */}
        {state === 'chat' && (
          <div className="qstate active">
            <div className="qhdr">
              <div className="qhdr-l">
                <span className="q-page-title">Let's plan your quiz</span>
                <span className="badge b-violet b-pulse">CHAT</span>
              </div>
              <div className="qhdr-r">
                <span style={{ fontSize: 12, color: 'var(--t3)' }}>Configure your quiz in the panel →</span>
              </div>
            </div>
            <div className="chat-body" style={{ overflowY: 'auto' }}>
              {!q().chatStarted ? (
                <div className="chat-start-screen">
                  <div style={{ fontSize: 42, opacity: 0.35 }}>💬</div>
                  <div className="f-h2">Ready when you are</div>
                  <div style={{ fontSize: 13.5, color: 'var(--t2)', maxWidth: 320, lineHeight: 1.6 }}>
                    Tell the AI your topics, question count, and any weak areas to prioritise.
                  </div>
                  <button className="btn btn-primary btn-lg" onClick={startChat} style={{ marginTop: 4 }}>
                    Start Chat
                  </button>
                </div>
              ) : (
                <>
                  <ChatBubbles messages={msgs.map((m) => ({ role: m.r === 'user' ? 'user' : 'ai', text: m.t, typing: m.typing }))} />
                  <div className="chat-footer">
                    <ChatInput
                      placeholder="Type a message…"
                      onSend={sendMsg}
                      disabled={q().sendBusy}
                      extra={
                        <button className="btn btn-primary" onClick={beginPipeline}>
                          Generate Quiz →
                        </button>
                      }
                    />
                  </div>
                </>
              )}
            </div>
          </div>
        )}

        {/* STATE: PIPELINE */}
        {state === 'pipeline' && (
          <div className="qstate active">
            <div className="qhdr">
              <div className="qhdr-l">
                <span className="q-page-title">Generating your quiz</span>
                <span className="badge b-amber b-pulse">{P_BADGE[Math.min(q().pStep, 3)]}</span>
              </div>
              <div className="qhdr-r">
                <button className="btn btn-ghost btn-sm" onClick={doPeek}>← Back to Chat</button>
                <button className="btn btn-secondary btn-sm" onClick={doCancel}>✕ Cancel</button>
              </div>
            </div>
            <div className="pipeline-body">
              <div className="pipeline-card">
                <div className="pipeline-card-head">
                  <div className="pipeline-stage-label">{pMsg.lbl}</div>
                  <div className="pipeline-main-msg">{pMsg.main}</div>
                  <div className="pipeline-sub-msg">{pMsg.sub}</div>
                </div>
                <div className="pipeline-stages">
                  {[0, 1, 2, 3].map((i) => {
                    const cls = i < q().pStep ? 'done' : i === q().pStep ? 'active' : 'idle';
                    return (
                      <div className={`p-stage ${cls}`} key={i}>
                        <div className="p-stage-node">{i < q().pStep ? '✓' : i === q().pStep ? '↻' : i + 1}</div>
                        <div className="p-stage-text">
                          <div className="p-stage-name">
                            {['Planning', 'Finding questions', 'Ordering', 'Final checks'][i]}
                          </div>
                          {i === q().pStep && <div className="p-stage-detail">{P_DETAIL[i]}</div>}
                        </div>
                        {i < q().pStep && <div className="p-stage-time">{i === 0 ? '1.8s' : '—'}</div>}
                      </div>
                    );
                  })}
                </div>
                <div className="pipeline-footer">
                  <div style={{ fontSize: 12.5, color: 'var(--t2)', flex: 1 }}>
                    Running in the background — peek at your chat any time.
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* STATE: PEEK */}
        {state === 'peek' && (
          <div className="qstate active">
            <div className="qhdr">
              <div className="qhdr-l">
                <span className="q-page-title">Your chat</span>
                <span className="badge b-amber b-pulse">PLANNING</span>
              </div>
              <div className="qhdr-r">
                <button className="btn btn-secondary btn-sm" onClick={doCancel}>✕ Cancel</button>
              </div>
            </div>
            <div className="chat-body" style={{ flex: 1, overflowY: 'auto' }}>
              <ChatBubbles messages={msgs.map((m) => ({ role: m.r === 'user' ? 'user' : 'ai', text: m.t || '…' }))} />
            </div>
            <div className="peek-banner">
              <span className="peek-banner-txt">{pMsg.sub.replace('Searching', 'Still searching').replace('Analysing', 'Still analysing')}</span>
              <button
                className="btn btn-sm"
                style={{ background: 'rgba(255,255,255,.18)', color: '#fff', border: '1px solid rgba(255,255,255,.28)' }}
                onClick={resumePipeline}
              >
                Continue →
              </button>
            </div>
          </div>
        )}

        {/* STATE: CANCELLED */}
        {state === 'cancelled' && (
          <div className="qstate active">
            <div className="qhdr">
              <div className="qhdr-l">
                <span className="q-page-title">Cancelled</span>
                <span className="badge b-neutral">CANCELLED</span>
              </div>
            </div>
            <div className="cancelled-body">
              <div className="cancelled-inner">
                <div className="cancelled-ico">🚫</div>
                <div className="f-h1">Cancelled.</div>
                <p style={{ fontSize: 14, color: 'var(--t2)', lineHeight: 1.65, maxWidth: 340 }}>
                  The quiz generation was stopped. You can retry from where it left off, or go back to revise your chat.
                </p>
                <div className="flex-r g10 mt8">
                  <button className="btn btn-primary" onClick={doRetry}>Retry →</button>
                  <button className="btn btn-secondary" onClick={() => { q().state = 'chat'; bump(); }}>← Back to Chat</button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* STATE: QUIZ ACTIVE */}
        {state === 'active' && (
          <div className="qstate active">
            <div className="qhdr">
              <div className="qhdr-l">
                <span className="q-page-title">Quiz</span>
                <span className="badge b-violet">Q {n} / {total}</span>
              </div>
              <div className="qhdr-r">
                <div className="q-progress">
                  <div className="q-prog-track">
                    <div className="q-prog-fill" style={{ width: `${(n / total) * 100}%` }} />
                  </div>
                  <div className="q-prog-lbl">{n} of {total}</div>
                </div>
                <div className={timer.rem <= 10 && (qset.timerMode === 'perQ' || (qset.timerMode === 'total' && timer.totalRem <= 30)) ? 'q-timer low' : 'q-timer'}
                  style={{ display: qset.timerMode === 'off' ? 'none' : undefined }}
                  title="Time left for this question"
                >
                  ⏱ <span>{fmtT(timer.rem)}</span>
                  {qset.timerMode === 'total' && <span>{' / ' + fmtT(timer.totalRem)}</span>}
                </div>
                <div className="qmap-wrap">
                  <button className="btn btn-secondary btn-sm" onClick={() => { q().qmapOpen = !q().qmapOpen; bump(); }}>
                    Questions
                  </button>
                  {q().qmapOpen && (
                    <div className="qmap-pop">
                      <div className="qmap-grid">
                        {allQs().map((qq, i) => {
                          const an = q().ans[i];
                          let cls = 'qmap-chip';
                          if (i === cur) cls += ' cur';
                          else if (qset.evalOn && an.submitted && an.fb && an.fb.type === 'wrong') cls += ' wrong';
                          else if (qset.evalOn && (an.skipped || (an.fb && an.fb.skipped))) cls += ' skip';
                          else if (qset.evalOn && an.submitted) cls += ' ok';
                          else if (an.sel != null || an.submitted) cls += ' ans';
                          return (
                            <button className={cls} key={i} onClick={() => gotoQ(i)}>
                              {i + 1}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
                <button className="btn btn-danger btn-sm" onClick={endQuiz}>■ End & Get Report</button>
              </div>
            </div>
            <div className="quiz-active-layout">
              <div className="q-pane">
                <div className="sim-banner" style={{ display: qd.isSim ? 'flex' : 'none' }}>
                  <span className="sim-ico">🧪</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 800, color: 'var(--em-tx)', fontSize: 13.5, marginBottom: 3 }}>
                      SIMULATION REQUIRED
                    </div>
                    <div style={{ fontSize: 13, color: 'var(--t2)' }}>{qd.simInstr ?? 'Run the simulation, then answer below.'}</div>
                  </div>
                  <button className="btn btn-sm btn-secondary" onClick={() => alert('Simulation would launch as an external process.')}>
                    ▶ Launch Simulation
                  </button>
                </div>
                <div className="q-card">
                  <div className="q-card-bar">
                    <span style={{ color: '#fff', fontSize: 11.5, fontWeight: 800, letterSpacing: '.05em' }}>
                      {qd.type}{qd.isSim ? ' · Sim' : ''} · Section {qd.sec}
                    </span>
                    <span className="badge" style={{ background: 'rgba(255,255,255,.18)', color: '#fff', fontSize: 10.5 }}>
                      {qd.pacing}
                    </span>
                  </div>
                  <div className="q-card-body">{qd.text}</div>
                </div>
                <div className="flex-c g8">
                  <div className="ans-label">Your answer</div>
                  {qd.type !== 'Written' && qd.opts && qd.opts.length > 0 && (
                    <div className="flex-c" style={{ gap: 8 }}>
                      {qd.opts.map((o, i) => {
                        let cls = 'mcq-opt';
                        if (qset.evalOn && a.submitted && a.sel != null) {
                          if (i === qd.correct) cls += ' correct-a';
                          else if (i === a.sel) cls += ' wrong-a';
                        } else if (a.sel != null && a.sel === i) cls += ' sel';
                        return (
                          <div
                            className={cls}
                            key={i}
                            style={qset.evalOn && a.submitted ? { pointerEvents: 'none' } : undefined}
                            onClick={() => selectOpt(i)}
                          >
                            <div className="opt-circle" />
                            <span>{o}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                  {qd.type === 'Written' && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      <textarea
                        className="written-area"
                        placeholder="Write your answer here… Markdown and $…$ math notation are fine."
                        value={a.written}
                        onChange={(e) => saveWritten(e.target.value)}
                      />
                    </div>
                  )}
                  {!(qd.type === 'Written') && (!qd.opts || qd.opts.length === 0) && (
                    <div>
                      <div className="flex-r g6" style={{ color: 'var(--em-tx)', fontSize: 13, marginBottom: 8 }}>
                        <span>⚠</span>
                        <span>No answer options were available for this question.</span>
                      </div>
                      <textarea
                        className="written-area"
                        placeholder="Type your answer…"
                        value={a.written}
                        onChange={(e) => saveWritten(e.target.value)}
                      />
                    </div>
                  )}
                  <div className="ans-actions mt4">
                    {qset.evalOn ? (
                      a.submitted ? (
                        <button className="btn btn-primary" onClick={nextQ}>Next →</button>
                      ) : (
                        <>
                          <button className="btn btn-primary" onClick={submitAns}>Submit Answer</button>
                          <button className="btn btn-secondary" onClick={skipQ}>Skip →</button>
                        </>
                      )
                    ) : qset.autoNext ? (
                      <>
                        <button className="btn btn-primary" onClick={submitAns}>Answer & Next →</button>
                        <button className="btn btn-secondary" onClick={skipQ}>Skip →</button>
                      </>
                    ) : (
                      <button className="btn btn-primary" onClick={nextQ}>Next →</button>
                    )}
                    <button className="btn btn-ghost btn-sm" style={{ display: cur > 0 ? undefined : 'none' }} onClick={prevQ}>
                      ← Back
                    </button>
                    {!qset.evalOn && (
                      <button
                        className={qset.autoNext ? 'auto-quick on' : 'auto-quick'}
                        onClick={() => setQset({ autoNext: !qset.autoNext })}
                        title="Auto-advance to the next question after answering"
                      >
                        Auto Next: {qset.autoNext ? 'On' : 'Off'}
                      </button>
                    )}
                    {q().errVisible && <span className="ans-err">{q().errText}</span>}
                  </div>
                </div>
              </div>

              {/* Feedback panel (dark) */}
              <div className={q().fbCollapsed ? 'fb-panel collapsed' : 'fb-panel'}>
                <div className="fb-head">
                  <div className="fb-panel-title">Feedback</div>
                  <button className="fb-toggle" onClick={() => { q().fbCollapsed = !q().fbCollapsed; bump(); }} title="Toggle feedback panel">
                    ›
                  </button>
                </div>
                <div className="fb-body">
                  <div className="fb-evalseg">
                    <button className={qset.evalOn ? 'fb-eval-btn on' : 'fb-eval-btn'} onClick={() => setQset({ evalOn: true })} title="Mark answers immediately">
                      Live
                    </button>
                    <button className={qset.evalOn ? 'fb-eval-btn' : 'fb-eval-btn on'} onClick={() => setQset({ evalOn: false })} title="Mark everything at the end">
                      End of quiz
                    </button>
                  </div>
                  <div className="fb-mode-line">
                    {qset.evalOn ? 'Live evaluation ON — feedback appears after each answer.' : 'Evaluation OFF — answers are marked at the end of the quiz.'}
                  </div>
                  {a.fb && a.fb.type !== 'loading' && (
                    <div
                      className={`fb-verdict ${
                        a.fb.type === 'correct' ? 'fv-correct' : a.fb.type === 'wrong' ? 'fv-wrong' : a.fb.type === 'score' ? 'fv-score' : 'fv-neutral'
                      }`}
                    >
                      {a.fb.type === 'correct' ? '✓ Correct' : a.fb.type === 'wrong' ? '✗ Incorrect' : a.fb.type === 'score' ? `Score: ${a.fb.score}` : 'Skipped'}
                    </div>
                  )}
                  {a.fb && a.fb.type === 'loading' && <div className="fb-verdict fv-loading">Evaluating…</div>}
                  {a.fb && a.fb.type !== 'loading' && a.fb.txt && <div className="fb-text">{a.fb.txt}</div>}
                  {!a.fb && <div className="fb-placeholder">Answer a question to see AI feedback here.</div>}
                  <div style={{ marginTop: 'auto' }}>
                    {a.submitted && (
                      <button className="fb-next-btn" onClick={nextQ}>Next Question →</button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* STATE: REPORT */}
        {state === 'report' && (
          <div className="qstate active">
            <div className="qhdr">
              <div className="qhdr-l">
                <span className="q-page-title">Quiz complete</span>
                <span className="badge b-jade">REPORT</span>
              </div>
            </div>
            <div className="report-body" style={{ overflowY: 'auto' }}>
              <div className="f-h1">Your results</div>
              <div className="report-stats">
                <div className="report-stat">
                  <div className="rs-lbl">MCQ Score</div>
                  <div className="rs-val" style={{ color: 'var(--v)' }}>
                    {report.ok}
                    <span style={{ fontSize: 18, color: 'var(--t3)' }}>/{report.tot}</span>
                  </div>
                </div>
                <div className="report-stat">
                  <div className="rs-lbl">Written Score</div>
                  <div className="rs-val" style={{ color: 'var(--em)' }}>
                    {report.wPct != null ? report.wPct : '—'}
                    {report.wPct != null && <span style={{ fontSize: 18, color: 'var(--t3)' }}>%</span>}
                  </div>
                </div>
                <div className="report-stat">
                  <div className="rs-lbl">Skipped</div>
                  <div className="rs-val" style={{ color: 'var(--t3)' }}>{report.skipped}</div>
                  <div className="rs-note">excluded from score</div>
                </div>
                <div className="report-stat">
                  <div className="rs-lbl">Time used</div>
                  <div className="rs-val" style={{ color: 'var(--t2)' }}>{reportTime}</div>
                </div>
              </div>
              <div className="report-summary">
                <div className="f-h3" style={{ marginBottom: 12 }}>Summary</div>
                <p>
                  You showed solid command of Newton's Laws — correctly identifying the First and Third Laws under pressure. Your written answer on F = ma was strong in concept but lacked the explicit proportionality statement and a labelled real-world example, which cost you marks.
                </p>
                <p style={{ marginTop: 10 }}>
                  Stoichiometry continues to be a gap: both mole-ratio questions were skipped. A focused 20-minute review of limiting reagents and molar mass calculation would likely push your accuracy above 70% on your next attempt.
                </p>
              </div>
              <div className="report-times">
                <div className="f-h3" style={{ marginBottom: 4 }}>Time per question</div>
                {allQs().map((qq, i) => {
                  const an = q().ans[i] ?? newAns();
                  const secs = an.timeSpent;
                  const tag = an.skipped ? ' · skipped' : an.submitted ? '' : ' · unanswered';
                  return (
                    <div className="rep-time-row" key={i}>
                      <span>Q{i + 1} · {qq.type}{tag}</span>
                      <span className={secs >= 60 ? 'rep-time-slow' : ''}>⏱ {fmtT(secs)}</span>
                    </div>
                  );
                })}
              </div>
              <div className="report-actions">
                <button className="btn btn-primary btn-lg" onClick={newQuiz}>Start New Quiz</button>
                <button className="btn btn-secondary btn-lg" onClick={() => onNavigate('history')}>Review This Quiz →</button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* QUIZ SETTINGS PANEL */}
      <div className={q().qspCollapsed ? 'qsp collapsed' : 'qsp'} style={{ display: showQSP ? undefined : 'none' }}>
        <div className="qsp-header">
          <span className="qsp-title">Quiz settings</span>
          <button className="qsp-toggle-btn" onClick={() => { q().qspCollapsed = !q().qspCollapsed; bump(); }} title="Toggle settings panel">
            ›
          </button>
        </div>
        <div className="qsp-icon-strip">
          <div className="qsp-strip-ico has-setting" title="Skip mode" onClick={() => { q().qspCollapsed = false; bump(); }}>⏭</div>
          <div className="qsp-strip-ico has-setting" title="Question types" onClick={() => { q().qspCollapsed = false; bump(); }}>📝</div>
          <div className="qsp-strip-ico has-setting" title="Topics" onClick={() => { q().qspCollapsed = false; bump(); }}>📚</div>
        </div>
        <div className="qsp-body">
          <div>
            <div className="qsp-section-title">If I skip a question</div>
            <div className="seg" style={{ width: '100%' }}>
              <button className={q().skipMode === 0 ? 'seg-btn on w100' : 'seg-btn w100'} style={{ flex: 1 }} onClick={() => { q().skipMode = 0; bump(); }}>Count as 0</button>
              <button className={q().skipMode === 1 ? 'seg-btn on w100' : 'seg-btn w100'} style={{ flex: 1 }} onClick={() => { q().skipMode = 1; bump(); }}>Exclude</button>
            </div>
          </div>
          <div>
            <div className="qsp-section-title">Question types</div>
            <div className="flex-c g8">
              <div style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--t2)', marginBottom: 2 }}>Section A — Objective</div>
              <label className="type-cb"><input type="checkbox" defaultChecked /> Simulation</label>
              <label className="type-cb"><input type="checkbox" defaultChecked /> Non-simulation</label>
              <div style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--t2)', marginTop: 6, marginBottom: 2 }}>Section B — Theory</div>
              <label className="type-cb"><input type="checkbox" defaultChecked /> Simulation</label>
              <label className="type-cb"><input type="checkbox" defaultChecked /> Non-simulation</label>
            </div>
          </div>
          <div>
            <div className="qsp-section-title">Selected topics</div>
            <div className="topic-pills">
              <span className="topic-pill">Newton's Laws</span>
              <span className="topic-pill">Kinematics</span>
              <span className="topic-pill">Acids & Bases</span>
              <span className="topic-pill">Stoichiometry</span>
              <span className="topic-pill">Calculus</span>
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--t3)', marginTop: 8 }}>
              Manage in <a style={{ cursor: 'pointer', color: 'var(--v)' }} onClick={() => onNavigate('settings')}>Settings</a>
            </div>
          </div>
          <div>
            <div className="qsp-section-title">Evaluation mode</div>
            <div className="seg" style={{ width: '100%' }}>
              <button className={qset.evalOn ? 'seg-btn on' : 'seg-btn'} style={{ flex: 1 }} onClick={() => setQset({ evalOn: true })}>Live</button>
              <button className={qset.evalOn ? 'seg-btn' : 'seg-btn on'} style={{ flex: 1 }} onClick={() => setQset({ evalOn: false })}>End of quiz</button>
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--t3)', marginTop: 6, lineHeight: 1.5 }}>{evalHint}</div>
          </div>
          <div className={qset.evalOn ? 'auto-locked' : ''}>
            <div className="qsp-section-title">Auto next</div>
            <div className="seg" style={{ width: '100%' }}>
              <button className={qset.autoNext ? 'seg-btn on' : 'seg-btn'} style={{ flex: 1 }} onClick={() => setQset({ autoNext: true })}>On</button>
              <button className={qset.autoNext ? 'seg-btn' : 'seg-btn on'} style={{ flex: 1 }} onClick={() => setQset({ autoNext: false })}>Off</button>
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--t3)', marginTop: 6, lineHeight: 1.5 }}>{autoHint}</div>
          </div>
          <div>
            <div className="qsp-section-title">Timing</div>
            <div className="seg" style={{ width: '100%' }}>
              <button className={qset.timerMode === 'off' ? 'seg-btn on' : 'seg-btn'} style={{ flex: 1 }} onClick={() => setQset({ timerMode: 'off' })}>Off</button>
              <button className={qset.timerMode === 'perQ' ? 'seg-btn on' : 'seg-btn'} style={{ flex: 1 }} onClick={() => setQset({ timerMode: 'perQ' })}>Per Q</button>
              <button className={qset.timerMode === 'total' ? 'seg-btn on' : 'seg-btn'} style={{ flex: 1 }} onClick={() => setQset({ timerMode: 'total' })}>Total</button>
            </div>
            {qset.timerMode === 'perQ' && (
              <div className="seg" style={{ width: '100%', marginTop: 8 }}>
                {[30, 60, 90].map((s) => (
                  <button key={s} className={qset.timerPerQ === s ? 'seg-btn on' : 'seg-btn'} style={{ flex: 1 }} onClick={() => setQset({ timerPerQ: s })}>
                    {s}s
                  </button>
                ))}
              </div>
            )}
            {qset.timerMode === 'total' && (
              <>
                <div className="seg" style={{ width: '100%', marginTop: 8 }}>
                  {[5, 10, 15].map((m) => (
                    <button key={m} className={qset.timerTotal === m ? 'seg-btn on' : 'seg-btn'} style={{ flex: 1 }} onClick={() => setQset({ timerTotal: m })}>
                      {m}m
                    </button>
                  ))}
                </div>
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--t2)', marginTop: 10 }}>When time runs out</div>
                <div className="seg" style={{ width: '100%', marginTop: 6 }}>
                  <button className={qset.totalExpiry === 'end' ? 'seg-btn on' : 'seg-btn'} style={{ flex: 1 }} onClick={() => setQset({ totalExpiry: 'end' })}>End quiz</button>
                  <button className={qset.totalExpiry === 'continue' ? 'seg-btn on' : 'seg-btn'} style={{ flex: 1 }} onClick={() => setQset({ totalExpiry: 'continue' })}>Keep going</button>
                </div>
              </>
            )}
            <div style={{ fontSize: 11.5, color: 'var(--t3)', marginTop: 6, lineHeight: 1.5 }}>{timerHint}</div>
          </div>
        </div>
      </div>
      </div>
    </section>
  );
}
