import { useEffect, useState } from 'react';
import { getDashboard, getUser } from '../api';
import type { DashboardData, RecentQuiz, SubjectStat, WeakTopic } from '../types';

interface Props {
  onNavigate: (screen: string) => void;
  active: boolean;
}

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

function fillClass(pct: number): string {
  if (pct >= 80) return 'fill-ja';
  if (pct >= 60) return 'fill-em';
  return 'fill-ro';
}

function pctColor(pct: number): string {
  if (pct >= 80) return 'var(--ja-tx)';
  if (pct >= 60) return 'var(--em-tx)';
  return 'var(--ro-tx)';
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  const day = String(d.getDate()).padStart(2, '0');
  const month = d.toLocaleString('en', { month: 'short' });
  return `${day} ${month}`;
}

function shortTopic(topics: string[]): string {
  const t = topics[0] || 'Untitled quiz';
  const m = t.match(/^[A-Za-z][A-Za-z ]*?\s*\((.+)\)$/);
  return m ? m[1].trim() : t;
}

function scoreLabel(q: RecentQuiz): string {
  const parts: string[] = [];
  if (q.mcq[1] > 0) parts.push(`${q.mcq[0]}/${q.mcq[1]}`);
  if (q.written_pct !== null) parts.push(`written ${q.written_pct}%`);
  return parts.join(' · ') || '—';
}

function SubjectRow({ subject }: { subject: SubjectStat }) {
  return (
    <div className="subj-row">
      <span className="subj-name" title={subject.name}>{subject.name}</span>
      <div className="subj-track">
        <div className={`subj-fill ${fillClass(subject.pct)}`} style={{ width: `${subject.pct}%` }} />
      </div>
      <span className="subj-pct" style={{ color: pctColor(subject.pct) }}>{subject.pct}%</span>
    </div>
  );
}

function WeakCard({ topic, onNavigate }: { topic: WeakTopic; onNavigate: (s: string) => void }) {
  const severity = topic.pct < 50 ? 'w-ro' : 'w-em';
  const color = topic.pct < 50 ? 'var(--ro)' : 'var(--em)';
  return (
    <div className={`weak-item ${severity}`}>
      <div className="weak-topic">{topic.topic}</div>
      <div className="weak-foot">
        <div className="weak-pct" style={{ color }}>{topic.pct}%</div>
        <div className="weak-actions">
          <button className="btn btn-sm btn-secondary" onClick={() => onNavigate('history')}>Review</button>
          <button className="btn btn-sm btn-secondary" onClick={() => onNavigate('tutor')}>Tutor</button>
        </div>
      </div>
    </div>
  );
}

function ActivityRow({ quiz, onNavigate }: { quiz: RecentQuiz; onNavigate: (s: string) => void }) {
  return (
    <div className="act-row" onClick={() => onNavigate('history')}>
      <span className="act-date">{fmtDate(quiz.created_at)}</span>
      <span className="act-topic" title={quiz.topics[0] || 'Untitled quiz'}>{shortTopic(quiz.topics)}</span>
      <span className="act-score">{scoreLabel(quiz)}</span>
      <span className="act-tags">
        {quiz.skipped > 0 && <span className="badge b-neutral" style={{ fontSize: 10 }}>skipped</span>}
        {!quiz.completed && <span className="badge b-rose" style={{ fontSize: 10 }}>incomplete</span>}
      </span>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <>
      <div className="dash-hero" style={{ marginBottom: 22 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div className="skel" style={{ width: 220, height: 26, background: 'rgba(255,255,255,.18)' }} />
          <div className="skel" style={{ width: 260, height: 14, background: 'rgba(255,255,255,.12)' }} />
        </div>
        <div className="skel" style={{ width: 140, height: 40, background: 'rgba(255,255,255,.18)' }} />
      </div>
      <div className="dash-grid">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <div className="card card-p">
            <div className="skel" style={{ width: 120, height: 14, marginBottom: 16 }} />
            <div className="skel" style={{ width: '100%', height: 26, marginBottom: 12 }} />
            <div className="skel" style={{ width: '100%', height: 26, marginBottom: 12 }} />
            <div className="skel" style={{ width: '100%', height: 26 }} />
          </div>
          <div className="card card-p">
            <div className="skel" style={{ width: 140, height: 14, marginBottom: 16 }} />
            <div className="skel" style={{ width: '100%', height: 34, marginBottom: 10 }} />
            <div className="skel" style={{ width: '100%', height: 34, marginBottom: 10 }} />
            <div className="skel" style={{ width: '100%', height: 34 }} />
          </div>
        </div>
        <div className="card card-p">
          <div className="skel" style={{ width: 120, height: 14, marginBottom: 16 }} />
          <div className="skel" style={{ width: '100%', height: 60 }} />
        </div>
      </div>
    </>
  );
}

export default function Dashboard({ onNavigate, active }: Props) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setError(null);
    setData(null);
    Promise.all([getDashboard(), getUser()])
      .then(([d, user]) => {
        setData(d);
        setName(user.name.charAt(0).toUpperCase() + user.name.slice(1));
      })
      .catch((err) => setError(String(err)));
  };

  useEffect(load, []);

  return (
    <section className={active ? 'screen active' : 'screen'} id="screen-dashboard">
      <div className="scroll-area">
        {error ? (
          <div className="empty">
            <div className="empty-ico">⚠️</div>
            <h3>Couldn't reach the sidecar</h3>
            <p>{error}</p>
            <button className="btn btn-secondary" onClick={load}>Retry</button>
          </div>
        ) : data ? (
          <>
            {data.setup_needed && (
              <div className="setup-banner" style={{ marginBottom: 16 }}>
                <span style={{ fontSize: 20 }}>📂</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--in)' }}>Set up your learning library</div>
                  <div style={{ fontSize: 12.5, color: 'var(--t2)', marginTop: 2 }}>
                    Go to Settings to scan your library and select topics.
                  </div>
                </div>
                <button className="btn btn-sm btn-secondary" onClick={() => onNavigate('settings')}>Open Settings →</button>
              </div>
            )}

            <div className="dash-hero">
              <div>
                <div className="dash-hero-greet">{greeting()}{name ? `, ${name}` : ''} 👋</div>
                <div className="dash-hero-stats mt8">
                  <strong>{data.quizzes}</strong> quizzes · <strong>{data.questions}</strong> questions answered ·{' '}
                  <strong>{data.avg_pct}%</strong> average
                </div>
              </div>
              <button className="btn btn-primary btn-lg" onClick={() => onNavigate('quiz')}>Start New Quiz →</button>
            </div>

            <div className="dash-grid">
              <div className="card card-p">
                <div className="dash-section-label">Subject mastery</div>
                {data.subjects.length ? (
                  <div className="subj-list" style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
                    {data.subjects.map((s) => <SubjectRow key={s.name} subject={s} />)}
                  </div>
                ) : (
                  <div className="c3" style={{ fontSize: 13.5 }}>No quiz data yet — your subjects will appear here.</div>
                )}
              </div>

              <div className="card card-p">
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                  <div className="dash-section-label" style={{ marginBottom: 0 }}>Recent activity</div>
                  <button className="btn btn-ghost btn-sm" onClick={() => onNavigate('history')}>All →</button>
                </div>
                {data.recent.length ? (
                  <div className="activity-list">
                    {data.recent.map((q) => <ActivityRow key={q.quiz_id} quiz={q} onNavigate={onNavigate} />)}
                  </div>
                ) : (
                  <div className="c3" style={{ fontSize: 13.5 }}>No quizzes taken yet.</div>
                )}
              </div>

              <div className="card card-p dash-full">
                <div className="dash-section-label">Needs attention</div>
                {data.weak_topics.length ? (
                  <div id="weak-list">
                    {data.weak_topics.map((w) => <WeakCard key={w.topic} topic={w} onNavigate={onNavigate} />)}
                  </div>
                ) : (
                  <div className="c3" style={{ fontSize: 13.5 }}>Nothing flagged — nice work.</div>
                )}
              </div>
            </div>
          </>
        ) : (
          <DashboardSkeleton />
        )}
      </div>
    </section>
  );
}
