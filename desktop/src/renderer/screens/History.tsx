import { useEffect, useState } from 'react';
import { getHistory, getHistoryDetail } from '../api';
import RichText from '../components/RichText';
import type { HistoryDetail, QuizSummary } from '../types';

interface Props {
  onNavigate: (screen: string) => void;
  active: boolean;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

function pctColor(pct: number): string {
  if (pct >= 80) return 'var(--ja-tx)';
  if (pct >= 60) return 'var(--em-tx)';
  return 'var(--ro-tx)';
}

function short(q: string, n = 48): string {
  return q.length > n ? q.substring(0, n) + '…' : q;
}

export default function History({ active }: Props) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [quizzes, setQuizzes] = useState<QuizSummary[]>([]);
  const [selQuiz, setSelQuiz] = useState<QuizSummary | null>(null);
  const [detail, setDetail] = useState<HistoryDetail | null>(null);
  const [selQ, setSelQ] = useState(0);
  const [railOpen, setRailOpen] = useState(false);

  const load = () => {
    setLoading(true);
    setError(null);
    getHistory()
      .then((d) => {
        setQuizzes(d.quizzes);
        setLoading(false);
      })
      .catch((e) => {
        setError(String(e.message ?? e));
        setLoading(false);
      });
  };

  useEffect(load, []);

  const selectQuiz = (q: QuizSummary) => {
    setSelQuiz(q);
    setRailOpen(true);
    setSelQ(0);
    setDetail(null);
    getHistoryDetail(q.quiz_id)
      .then((d) => {
        setDetail(d);
        setSelQ(0);
      })
      .catch((e) => setError(String(e.message ?? e)));
  };

  const backToList = () => {
    setRailOpen(false);
    setSelQuiz(null);
    setDetail(null);
  };

  const curQ = detail && detail.questions.length ? detail.questions[selQ] : null;

  return (
    <section className={active ? 'screen active' : 'screen'} id="screen-history">
      <div className="qhdr">
        <div className="qhdr-l"><span className="q-page-title">History</span></div>
      </div>
      <div className="hist-layout" style={{ width: '100%', height: '100%' }}>
      <div className="hist-list">
        <div className="hist-list-hdr">
          <span className="f-label">Recent quizzes</span>
        </div>
        {loading ? (
          <div className="empty">
            <div className="empty-ico">⏳</div>
            <h3>Loading your history…</h3>
          </div>
        ) : error ? (
          <div className="empty">
            <div className="empty-ico">⚠️</div>
            <h3>Couldn't load history</h3>
            <p>{error}</p>
            <button className="btn btn-secondary" onClick={load}>Try again</button>
          </div>
        ) : quizzes.length === 0 ? (
          <div className="empty">
            <div className="empty-ico">📋</div>
            <h3>No quizzes yet</h3>
            <p>Complete a quiz and it will appear here.</p>
          </div>
        ) : (
          quizzes.map((q) => (
            <div
              className={selQuiz && selQuiz.quiz_id === q.quiz_id ? 'hist-qz-row active' : 'hist-qz-row'}
              key={q.quiz_id}
              onClick={() => selectQuiz(q)}
            >
              <div className="hist-qz-title">{q.topic || 'Untitled quiz'}</div>
              <div className="hist-qz-meta">
                {fmtDate(q.created_at)} · {q.completed ? 'Completed' : 'Incomplete'} · <span style={{ color: pctColor(q.avg_pct) }}>{q.avg_pct}%</span>
              </div>
            </div>
          ))
        )}
      </div>

      <div className="q-detail-pane">
        {!curQ || !detail ? (
          <div className="empty">
            <div className="empty-ico">📋</div>
            <h3>Select a quiz to review</h3>
            <p>Choose a quiz from the list to see your answers and feedback.</p>
          </div>
        ) : (
          <>
            <div className="flex-r g8">
              <button className="btn btn-ghost btn-sm" onClick={backToList}>← All Quizzes</button>
              <span className="badge b-neutral">Q{curQ.number} · {curQ.q_type}</span>
              <span className="badge b-neutral">{detail.topic}</span>
            </div>
            <div className="q-card">
              <div className="q-card-bar">
                <span style={{ color: '#fff', fontSize: 11.5, fontWeight: 800 }}>
                  {curQ.q_type} · {detail.topic}
                </span>
              </div>
              <div className="q-card-body"><RichText text={curQ.question} /></div>
            </div>
            {curQ.skipped ? (
              <div className="hist-ans-block">
                <div className="hist-ans-lbl">Your Answer</div>
                <div className="hist-ans-val" style={{ color: 'var(--t3)', fontStyle: 'italic' }}>Skipped</div>
              </div>
            ) : curQ.q_type === 'MCQ' ? (
              <>
                <div className="hist-ans-block">
                  <div className="hist-ans-lbl">Your Answer</div>
                  <div className="hist-ans-val" style={{ color: curQ.is_correct ? 'var(--ja-tx)' : 'var(--ro-tx)' }}>
                    {curQ.user_answer || '—'}
                  </div>
                </div>
                {!curQ.is_correct && curQ.correct_answer && (
                  <div className="hist-ans-block">
                    <div className="hist-ans-lbl">Correct Answer</div>
                    <div className="hist-ans-val" style={{ color: 'var(--ja-tx)' }}><RichText text={curQ.correct_answer} /> ✓</div>
                  </div>
                )}
              </>
            ) : (
              <>
                <div className="hist-ans-block">
                  <div className="hist-ans-lbl">Your Answer</div>
                  <div className="hist-ans-val">{curQ.user_answer || '—'}</div>
                </div>
                {curQ.correct_answer && (
                  <div className="hist-ans-block">
                    <div className="hist-ans-lbl">Standard Answer</div>
                    <div className="hist-ans-val"><RichText text={curQ.correct_answer} /></div>
                  </div>
                )}
                {curQ.score != null && (
                  <div className="hist-ans-block">
                    <div className="hist-ans-lbl">Score</div>
                    <div className="hist-ans-val" style={{ fontWeight: 800, color: curQ.score >= 0.5 ? 'var(--ja-tx)' : 'var(--ro-tx)' }}>
                      {curQ.score.toFixed(2)}
                    </div>
                  </div>
                )}
                {curQ.ai_feedback && (
                  <div className="hist-ans-block">
                    <div className="hist-ans-lbl">AI Feedback</div>
                    <div className="hist-ans-val"><RichText text={curQ.ai_feedback} /></div>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>

      <div className="hist-q-rail" style={{ display: railOpen ? 'flex' : 'none' }}>
        <div className="hist-q-rail-title">Questions</div>
        {detail && detail.questions.map((q, i) => {
          let mc = 'qm-skip';
          let mt = '⊘';
          if (q.skipped) { mc = 'qm-skip'; mt = '⊘'; }
          else if (q.is_correct === true) { mc = 'qm-ok'; mt = '✓'; }
          else if (q.is_correct === false) { mc = 'qm-bad'; mt = '✗'; }
          else if (q.score != null) { mc = 'qm-score'; mt = String(Math.round(q.score * 100)); }
          return (
            <div className={i === selQ ? 'hist-q-row active' : 'hist-q-row'} key={q.number} onClick={() => setSelQ(i)}>
              <div className={`q-mark ${mc}`}>{mt}</div>
              <div>Q{q.number}: {short(q.question)}</div>
            </div>
          );
        })}
      </div>
      </div>
    </section>
  );
}
