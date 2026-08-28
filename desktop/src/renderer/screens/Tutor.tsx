import { useEffect, useState } from 'react';
import { getHistory, getHistoryDetail } from '../api';
import { ChatBubbles } from '../components/ChatComposer';
import type { QuizSummary } from '../types';

interface Props {
  active: boolean;
}

interface TutorMsg {
  r: 'user' | 'ai';
  t: string;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

export default function Tutor({ active }: Props) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [quizzes, setQuizzes] = useState<QuizSummary[]>([]);
  const [selQuizId, setSelQuizId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Awaited<ReturnType<typeof getHistoryDetail>> | null>(null);
  const [selQ, setSelQ] = useState<number | null>(null);
  const [threads, setThreads] = useState<Record<string, TutorMsg[]>>({});
  const [busy, setBusy] = useState(false);
  const [ctxShown, setCtxShown] = useState(false);

  useEffect(() => {
    getHistory()
      .then((d) => {
        setQuizzes(d.quizzes);
        setLoading(false);
        if (d.quizzes.length) setSelQuizId(d.quizzes[0].quiz_id);
      })
      .catch((e) => {
        setError(String(e.message ?? e));
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    if (!selQuizId) return;
    setDetail(null);
    setSelQ(null);
    setCtxShown(false);
    getHistoryDetail(selQuizId)
      .then(setDetail)
      .catch((e) => setError(String(e.message ?? e)));
  }, [selQuizId]);

  const selQuiz = quizzes.find((q) => q.quiz_id === selQuizId) || null;
  const threadKey = selQuizId && selQ != null ? `${selQuizId}-${selQ}` : '';
  const thread = threadKey ? threads[threadKey] || [] : [];
  const curQ = detail && selQ != null ? detail.questions[selQ] : null;

  const sendTutor = (text: string) => {
    if (!threadKey || !curQ) return;
    const userMsg: TutorMsg = { r: 'user', t: text };
    setThreads((prev) => ({ ...prev, [threadKey]: [...(prev[threadKey] || []), userMsg] }));
    setBusy(true);
    setTimeout(() => {
      setThreads((prev) => ({
        ...prev,
        [threadKey]: [
          ...(prev[threadKey] || []),
          { r: 'ai', t: `Let me walk you through that. ${curQ.correct_answer} Does that help clarify things? Feel free to ask a follow-up.` },
        ],
      }));
      setBusy(false);
    }, 900);
  };

  const yourAns = curQ && (curQ.skipped ? 'Skipped' : curQ.user_answer || '—');

  return (
    <section className={active ? 'screen active' : 'screen'} id="screen-tutor">
      <div className="qhdr">
        <div className="qhdr-l"><span className="q-page-title">Tutor</span></div>
      </div>
      <div className="tutor-layout">
        <div className="tutor-ql">
          <div className="tutor-ql-top">
            <div className="tutor-ql-hdr">Tutoring on</div>
            <select
              className="tutor-quiz-picker"
              value={selQuizId ?? ''}
              onChange={(e) => setSelQuizId(e.target.value)}
            >
              {quizzes.map((q) => (
                <option key={q.quiz_id} value={q.quiz_id}>
                  {q.topic || 'Untitled quiz'} · {fmtDate(q.created_at)}
                </option>
              ))}
            </select>
          </div>
          {loading ? (
            <div className="empty">
              <div className="empty-ico">⏳</div>
              <h3>Loading…</h3>
            </div>
          ) : error ? (
            <div className="empty">
              <div className="empty-ico">⚠️</div>
              <h3>Couldn't load</h3>
              <p>{error}</p>
            </div>
          ) : quizzes.length === 0 ? (
            <div className="empty">
              <div className="empty-ico">💬</div>
              <h3>No quizzes yet</h3>
              <p>Complete a quiz to get questions you can be tutored on.</p>
            </div>
          ) : (
            (detail ? detail.questions : []).map((q) => (
              <div
                className={selQ === q.number - 1 ? 'tutor-qi active' : 'tutor-qi'}
                key={q.number}
                onClick={() => {
                  setSelQ(q.number - 1);
                  setCtxShown(true);
                }}
              >
                <div className="tutor-qi-num">Q{q.number} · {q.q_type}</div>
                <div className="tutor-qi-prev">{q.question}</div>
              </div>
            ))
          )}
        </div>
        <div className="tutor-main">
          {ctxShown && curQ && (
            <div className="tutor-ctx" style={{ display: 'block' }}>
              <div className="tutor-ctx-card">
                <div>
                  <div className="tutor-fld-lbl">Question</div>
                  <div className="tutor-fld-val">{curQ.question}</div>
                </div>
                <div>
                  <div className="tutor-fld-lbl">Your Answer</div>
                  <div className="tutor-fld-val">{yourAns}</div>
                </div>
              </div>
            </div>
          )}
          <div className="tutor-chat">
            {!curQ || !ctxShown ? (
              <div className="empty">
                <div className="empty-ico">💬</div>
                <h3>Select a question to start tutoring</h3>
                <p>Choose from the list to open a dedicated tutoring thread.</p>
              </div>
            ) : thread.length === 0 ? (
              <div style={{ fontSize: 13, color: 'var(--t3)', textAlign: 'center', marginTop: 28 }}>
                Ask anything about this question to start your tutoring session.
              </div>
            ) : (
              <ChatBubbles messages={thread.map((m) => ({ role: m.r === 'user' ? 'user' : 'ai', text: m.t }))} />
            )}
          </div>
          <div className="tutor-footer" style={{ display: curQ && ctxShown ? 'block' : 'none' }}>
            <div className="chat-row">
              <textarea
                className="chat-inp"
                placeholder="Ask anything about this question…"
                rows={1}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    const el = e.currentTarget;
                    const txt = el.value.trim();
                    if (!txt || busy) return;
                    el.value = '';
                    el.style.height = 'auto';
                    sendTutor(txt);
                  }
                }}
              />
              <button
                className="btn btn-secondary"
                disabled={busy}
                onClick={(e) => {
                  const el = e.currentTarget.previousElementSibling as HTMLTextAreaElement | null;
                  const txt = el ? el.value.trim() : '';
                  if (!txt || busy) return;
                  if (el) {
                    el.value = '';
                    el.style.height = 'auto';
                  }
                  sendTutor(txt);
                }}
              >
                Send
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
