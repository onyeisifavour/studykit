import { useCallback, useEffect, useState } from 'react';
import Menu from '../components/Menu';
import {
  branchInstance,
  deleteArtifact,
  deleteInstance,
  deriveArtifact,
  getArtifact,
  getArtifacts,
  getInstance,
  getInstances,
  startInstance,
} from '../api';
import type {
  ArtifactDetail,
  ArtifactSummary,
  InstanceSummary,
  TimeEntry,
} from '../types';

type Tab = 'set' | 'states';

/** A working copy of the set's question order. `src` is the question's number in
 *  the *stored* artifact, so reordering and removal are tracked by source
 *  identity while the displayed/saved numbering stays a clean 1..N. */
type Draft = { src: number; text: string; type: string; topic: string }[];

function short(s: string, n = 110): string {
  const t = (s ?? '').replace(/\s+/g, ' ').trim();
  return t.length > n ? t.slice(0, n - 1) + '…' : t;
}

function fmtT(secs: number): string {
  const s = Math.max(0, Math.round(secs));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
    : `${m}:${String(sec).padStart(2, '0')}`;
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function toDraft(a: ArtifactDetail): Draft {
  return a.questions.map((q) => ({
    src: q.number,
    text: q.question_text,
    type: q.q_type,
    topic: q.topic,
  }));
}

export default function Artifacts({
  active,
  onResume,
}: {
  active: boolean;
  /** Opens a saved state in the quiz screen. */
  onResume: (instanceId: string, workQuizId: string) => void;
}) {
  const [tab, setTab] = useState<Tab>('set');
  const [list, setList] = useState<ArtifactSummary[]>([]);
  const [states, setStates] = useState<InstanceSummary[]>([]);
  const [selState, setSelState] = useState<InstanceSummary | null>(null);
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [detail, setDetail] = useState<ArtifactDetail | null>(null);
  const [draft, setDraft] = useState<Draft>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [a, s] = await Promise.all([getArtifacts(), getInstances()]);
      setList(a.artifacts);
      setStates(s.instances);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (active) void refresh();
  }, [active, refresh]);

  // Selecting a saved state pulls its full record so the time-entry log can be
  // shown — a paused run has no meaningful average, only this breakdown.
  const openState = (s: InstanceSummary) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    getInstance(s.instance_id)
      .then((d) => {
        setSelState(d);
        setEntries(d.entries);
      })
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setBusy(false));
  };

  // Hands the attempt back to the quiz screen, which reloads the working note
  // and jumps to the saved position.
  const resumeState = (s: InstanceSummary) => {
    if (busy || !s.work_quiz_id) return;
    onResume(s.instance_id, s.work_quiz_id);
  };

  const branchState = (s: InstanceSummary) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    setNote(null);
    branchInstance(s.instance_id)
      .then((child) => {
        setNote(`Branched a fresh attempt (${child.instance_id.slice(0, 8)}). The saved state is untouched.`);
        return refresh();
      })
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setBusy(false));
  };

  const dropState = (s: InstanceSummary) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    setNote(null);
    deleteInstance(s.instance_id)
      .then(() => {
        if (selState?.instance_id === s.instance_id) {
          setSelState(null);
          setEntries([]);
        }
        return refresh();
      })
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setBusy(false));
  };

  const open = (a: ArtifactSummary) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    setNote(null);
    getArtifact(a.artifact_id)
      .then((d) => {
        setDetail(d);
        setDraft(toDraft(d));
      })
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setBusy(false));
  };

  // Starts a fresh attempt at a quiz set and hands it straight to the quiz
  // screen. The set itself is only read, so every attempt is independent.
  const startSet = (a: ArtifactSummary) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    setNote(null);
    startInstance(a.artifact_id)
      .then((inst) => {
        if (!inst.work_quiz_id) {
          setError('That attempt has no working question set. Try starting it again.');
          return;
        }
        onResume(inst.instance_id, inst.work_quiz_id);
      })
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setBusy(false));
  };

  const backToList = () => {
    setDetail(null);
    setDraft([]);
    setError(null);
    setNote(null);
  };

  const move = (i: number, delta: number) => {
    setDraft((cur) => {
      const j = i + delta;
      if (j < 0 || j >= cur.length) return cur;
      const next = cur.slice();
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  };

  const remove = (i: number) => {
    setDraft((cur) => cur.filter((_, k) => k !== i));
  };

  const save = () => {
    if (!detail || busy || draft.length === 0) return;
    setBusy(true);
    setError(null);
    setNote(null);
    deriveArtifact(detail.artifact_id, draft.map((q) => q.src))
      .then((r) => {
        setNote(
          r.created
            ? `Saved as a new quiz set (${r.artifact_id.slice(0, 6)}). The original is untouched.`
            : 'No changes to save — that set already exists.',
        );
        return refresh();
      })
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setBusy(false));
  };

  const duplicate = () => {
    if (!detail || busy) return;
    setBusy(true);
    setError(null);
    setNote(null);
    deriveArtifact(detail.artifact_id)
      .then((r) => {
        setNote(
          r.created
            ? `Duplicated as a new quiz set (${r.artifact_id.slice(0, 6)}).`
            : 'An identical quiz set already exists.',
        );
        return refresh();
      })
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setBusy(false));
  };

  const removeSet = (a: ArtifactSummary) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    setNote(null);
    deleteArtifact(a.artifact_id)
      .then(() => {
        if (detail?.artifact_id === a.artifact_id) backToList();
        return refresh();
      })
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setBusy(false));
  };

  // Compare source identity, not position — the displayed numbering is always
  // a clean 1..N so it can never reveal a pure reorder on its own.
  const dirty =
    detail !== null &&
    draft.map((q) => q.src).join(',') !==
      detail.questions.map((q) => q.number).join(',');

  return (
    <section className={active ? 'screen active' : 'screen'} id="screen-artifacts">
      <div className="qhdr">
        <div className="qhdr-l">
          <span className="q-page-title">Artifacts</span>
        </div>
        <div className="qhdr-r">
          <div className="seg">
            <button
              className={tab === 'set' ? 'seg-btn active' : 'seg-btn'}
              onClick={() => setTab('set')}
            >
              Quiz Set
            </button>
            <button
              className={tab === 'states' ? 'seg-btn active' : 'seg-btn'}
              onClick={() => setTab('states')}
            >
              Saved States
            </button>
          </div>
        </div>
      </div>

      <div className="hist-layout" style={{ width: '100%', height: '100%' }}>
        {tab === 'states' ? (
          <div className="hist-layout" style={{ width: '100%', height: '100%' }}>
            <div className="hist-list">
              <div className="hist-list-hdr">
                <span className="f-label">Saved states</span>
              </div>
              {note && (
                <div className="hist-inline-note">
                  <span>{note}</span>
                  <button type="button" onClick={() => setNote(null)} aria-label="Dismiss">
                    ✕
                  </button>
                </div>
              )}
              {error && (
                <div className="hist-inline-error">
                  <span>{error}</span>
                  <button type="button" onClick={() => setError(null)} aria-label="Dismiss">
                    ✕
                  </button>
                </div>
              )}
              {loading ? (
                <div className="empty">
                  <div className="empty-ico">⏳</div>
                  <h3>Loading saved states…</h3>
                </div>
              ) : states.length === 0 ? (
                <div className="empty">
                  <div className="empty-ico">💾</div>
                  <h3>No saved states yet</h3>
                  <p>
                    Start a quiz set and use <b>Save State</b> to park your progress
                    and come back to exactly where you left off.
                  </p>
                </div>
              ) : (
                states.map((s) => (
                  <div
                    className={
                      selState?.instance_id === s.instance_id
                        ? 'hist-qz-row active'
                        : 'hist-qz-row'
                    }
                    key={s.instance_id}
                    onClick={() => openState(s)}
                  >
                    <div className="hist-qz-title">{s.title || 'Untitled quiz'}</div>
                    <div className="hist-qz-meta">
                      {fmtDate(s.created_at)} · {s.answered}/{s.total_questions} answered
                      {s.status === 'completed' ? ' · Finished' : s.status === 'paused' ? ' · Paused' : ' · In progress'}
                      {s.marking_pending ? ' · ' : ' · '}
                      {s.marking_pending ? <span className="badge b-amber">PENDING AI MARKING</span> : fmtT(s.total_secs)}
                    </div>
                    <div className="hist-qz-menu" onClick={(e) => e.stopPropagation()}>
                      <Menu
                        ariaLabel={`Actions for ${s.title || 'saved state'}`}
                        items={[
                          ...(s.status !== 'completed'
                            ? [{
                                key: 'resume',
                                label: 'Resume where I left off',
                                disabled: busy || !s.work_quiz_id,
                                onSelect: () => resumeState(s),
                              }]
                            : []),
                          {
                            key: 'branch',
                            label: 'Branch a fresh attempt',
                            disabled: busy,
                            onSelect: () => branchState(s),
                          },
                          {
                            key: 'delete',
                            label: 'Delete saved state',
                            confirm: 'Click again to confirm',
                            danger: true,
                            disabled: busy,
                            onSelect: () => dropState(s),
                          },
                        ]}
                      />
                    </div>
                  </div>
                ))
              )}
            </div>

            <div className="q-detail-pane">
              {!selState ? (
                <div className="empty">
                  <div className="empty-ico">💾</div>
                  <h3>Select a saved state</h3>
                  <p>
                    A saved state keeps your answers and the time you have spent so
                    far. Branching starts a clean attempt from the same questions.
                  </p>
                </div>
              ) : (
                <>
                  <div className="flex-r g8 art-toolbar">
                    <span className="badge b-neutral">{selState.total_questions} questions</span>
                    <span className="badge b-neutral">{selState.subject}</span>
                    <span className={selState.status === 'paused' ? 'badge b-amber' : 'badge b-jade'}>
                      {selState.status.toUpperCase()}
                    </span>
                    {selState.marking_pending && (
                      <span className="badge b-amber">PENDING AI MARKING</span>
                    )}
                    <div className="art-toolbar-actions">
                      {selState.status === 'completed' ? (
                        <span className="art-timing-sub" style={{ marginTop: 0 }}>
                          This attempt is finished — branch a fresh one to try again.
                        </span>
                      ) : (
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={() => resumeState(selState)}
                          disabled={busy || !selState.work_quiz_id}
                        >
                          ⏵ Resume
                        </button>
                      )}
                      <button className="btn btn-secondary btn-sm" onClick={() => branchState(selState)} disabled={busy}>
                        Branch
                      </button>
                    </div>
                  </div>

                  <div className="art-timing">
                    <div className="rs-lbl">Total time</div>
                    <div className="rs-val">{fmtT(selState.total_secs)}</div>
                    <div className="art-timing-sub">
                      {selState.was_paused ? (
                        <>
                          Paused {selState.time_entries === 1 ? 'once' : `${selState.time_entries} times`} — an
                          average per question would be misleading, so here is the
                          breakdown instead.
                        </>
                      ) : (
                        <>Never paused, so this averages {selState.avg_secs != null ? selState.avg_secs.toFixed(1) : '—'}s per question.</>
                      )}
                    </div>
                  </div>

                  {selState.was_paused && (
                    <div className="art-entries">
                      <div className="f-label" style={{ marginBottom: 6 }}>Time entries</div>
                      {entries.map((e) => (
                        <div className="rep-time-row" key={e.index}>
                          <span>Stretch {e.index}</span>
                          <span className={e.elapsed_secs >= 180 ? 'rep-time-slow' : ''}>
                            {fmtT(e.elapsed_secs)}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        ) : (
          <>
            <div className="hist-list">
              <div className="hist-list-hdr">
                <span className="f-label">Quiz sets</span>
              </div>
              {note && (
                <div className="hist-inline-note">
                  <span>{note}</span>
                  <button type="button" onClick={() => setNote(null)} aria-label="Dismiss">
                    ✕
                  </button>
                </div>
              )}
              {error && (
                <div className="hist-inline-error">
                  <span>{error}</span>
                  <button type="button" onClick={() => setError(null)} aria-label="Dismiss">
                    ✕
                  </button>
                </div>
              )}
              {loading ? (
                <div className="empty">
                  <div className="empty-ico">⏳</div>
                  <h3>Loading your quiz sets…</h3>
                </div>
              ) : list.length === 0 ? (
                <div className="empty">
                  <div className="empty-ico">📦</div>
                  <h3>No quiz sets yet</h3>
                  <p>
                    Generate a quiz, or use <b>Retake as quiz set</b> on any History
                    entry, and it will show up here.
                  </p>
                </div>
              ) : (
                list.map((a) => (
                  <div
                    className={
                      detail?.artifact_id === a.artifact_id
                        ? 'hist-qz-row active'
                        : 'hist-qz-row'
                    }
                    key={a.artifact_id}
                    onClick={() => open(a)}
                  >
                    <div className="hist-qz-title">{a.title || 'Untitled quiz'}</div>
                    <div className="hist-qz-meta">
                      {fmtDate(a.created_at)} · {a.total_questions} questions ·{' '}
                      {a.subject}
                    </div>
                    <div className="hist-qz-menu" onClick={(e) => e.stopPropagation()}>
                      <Menu
                        ariaLabel={`Actions for ${a.title || 'Untitled quiz'}`}
                        items={[
                          {
                            key: 'start',
                            label: 'Start this quiz now',
                            disabled: busy,
                            onSelect: () => startSet(a),
                          },
                          {
                            key: 'duplicate',
                            label: 'Duplicate',
                            disabled: busy,
                            onSelect: () => {
                              if (!detail || detail.artifact_id !== a.artifact_id) {
                                setNote('Open this set first, then duplicate it.');
                                return;
                              }
                              duplicate();
                            },
                          },
                          {
                            key: 'delete',
                            label: 'Delete quiz set',
                            confirm: 'Click again to confirm',
                            danger: true,
                            disabled: busy,
                            onSelect: () => removeSet(a),
                          },
                        ]}
                      />
                    </div>
                  </div>
                ))
              )}
            </div>

            <div className="q-detail-pane">
              {!detail ? (
                <div className="empty">
                  <div className="empty-ico">📦</div>
                  <h3>Select a quiz set</h3>
                  <p>
                    Pick a set on the left to review it. Removing or reordering
                    questions and saving creates a brand new set — the original is
                    always kept.
                  </p>
                </div>
              ) : (
                <>
                  <div className="flex-r g8 art-toolbar">
                    <button className="btn btn-ghost btn-sm" onClick={backToList}>
                      ← All Quiz Sets
                    </button>
                    <span className="badge b-neutral">{draft.length} questions</span>
                    <span className="badge b-neutral">{detail.subject}</span>
                    <div className="art-toolbar-actions">
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={() => startSet({
                          artifact_id: detail.artifact_id,
                          created_at: detail.created_at,
                          source: detail.source,
                          topics: detail.topics,
                          title: detail.title,
                          subject: detail.subject,
                          total_questions: draft.length,
                        })}
                        disabled={busy || draft.length === 0}
                      >
                        Start this quiz
                      </button>
                      <button className="btn btn-secondary btn-sm" onClick={duplicate} disabled={busy}>
                        Duplicate
                      </button>
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={save}
                        disabled={busy || !dirty || draft.length === 0}
                      >
                        Save as new set
                      </button>
                    </div>
                  </div>
                  {detail.topics.length > 1 && (
                    <div className="topic-pills art-topics">
                      {detail.topics.map((t) => (
                        <span className="topic-pill" key={t}>
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="art-q-list">
                    {draft.map((q, i) => (
                      <div className="art-q" key={q.src}>
                        <span className="art-q-num">{i + 1}</span>
                        <div className="art-q-body">
                          <div className="art-q-text">{short(q.text, 150)}</div>
                          <div className="hist-qz-meta">
                            <span className="badge b-neutral">{q.type}</span>
                            {q.topic && <> · {q.topic}</>}
                          </div>
                        </div>
                        <div className="art-q-ctl">
                          <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => move(i, -1)}
                            disabled={busy || i === 0}
                            aria-label={`Move question ${i + 1} up`}
                            title="Move up"
                          >
                            ↑
                          </button>
                          <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => move(i, 1)}
                            disabled={busy || i === draft.length - 1}
                            aria-label={`Move question ${i + 1} down`}
                            title="Move down"
                          >
                            ↓
                          </button>
                          <button
                            className="btn btn-ghost btn-sm art-q-del"
                            onClick={() => remove(i)}
                            disabled={busy}
                            aria-label={`Remove question ${i + 1}`}
                            title="Remove"
                          >
                            ✕
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
