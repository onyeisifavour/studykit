import { useEffect, useRef, useState } from 'react';
import { getSettings, saveSettings, scanLibrary } from '../api';
import type { LibraryScan, SettingsData } from '../types';

interface Props {
  active: boolean;
}

type Pane = 'quiz' | 'lib' | 'ai';

const MASK = '••••••••';

const KEY_SLOTS = 4;

export default function Settings({ active }: Props) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [pane, setPane] = useState<Pane>('quiz');

  // quiz pane
  const [sections, setSections] = useState<SettingsData['sections'] | null>(null);
  const [shuffle, setShuffle] = useState<SettingsData['shuffle'] | null>(null);
  const [evalOn, setEvalOn] = useState(true);
  // timing (session-level, mirrors prototype QSET)
  const [tmode, setTmode] = useState<'off' | 'perQ' | 'total'>('off');
  const [tPerQ, setTPerQ] = useState(60);
  const [tTotal, setTTotal] = useState(10);
  const [tExpiry, setTExpiry] = useState<'end' | 'continue'>('end');

  // lib pane
  const [libRoot, setLibRoot] = useState('');
  const [scan, setScan] = useState<LibraryScan | null>(null);
  const [scanErr, setScanErr] = useState<string | null>(null);
  const [selPaths, setSelPaths] = useState<string[]>([]);
  const [scanning, setScanning] = useState(false);

  // ai pane
  const [providerMode, setProviderMode] = useState('cli_bridge');
  const [cliModel, setCliModel] = useState('');
  const [groqKeys, setGroqKeys] = useState<string[]>(['', '', '', '']);
  const [groqModel, setGroqModel] = useState('');
  const [orKeys, setOrKeys] = useState<string[]>(['', '', '', '']);
  const [orModel, setOrModel] = useState('');
  const [custUrl, setCustUrl] = useState('');
  const [custKey, setCustKey] = useState('');
  const [custModel, setCustModel] = useState('');

  const [note, setNote] = useState<string | null>(null);
  const noteTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    getSettings()
      .then((s) => {
        setSettings(s);
        setSections(s.sections);
        setShuffle(s.shuffle);
        setEvalOn(s.evaluation_on);
        setLibRoot(s.library_root);
        setSelPaths([...s.selected_topics]);
        setProviderMode(s.provider_mode === 'api' ? 'api' : 'cli_bridge');
        setCliModel(s.cli_model);
        setGroqKeys([...s.api.groq.keys].concat(Array(KEY_SLOTS).fill('')).slice(0, KEY_SLOTS));
        setGroqModel(s.api.groq.model);
        setOrKeys([...s.api.openrouter.keys].concat(Array(KEY_SLOTS).fill('')).slice(0, KEY_SLOTS));
        setOrModel(s.api.openrouter.model);
        setCustUrl(s.api.custom.url);
        setCustKey(s.api.custom.key);
        setCustModel(s.api.custom.model);
        setLoading(false);
      })
      .catch((e) => {
        setError(String(e.message ?? e));
        setLoading(false);
      });
  }, []);

  const showNote = (text: string) => {
    setNote(text);
    if (noteTimer.current) clearTimeout(noteTimer.current);
    noteTimer.current = setTimeout(() => setNote(null), 3000);
  };

  const persist = (patch: Partial<SettingsData>) => {
    saveSettings(patch)
      .then((s) => {
        setSettings(s);
        setSections(s.sections);
        setShuffle(s.shuffle);
        setEvalOn(s.evaluation_on);
        showNote('✓ Saved');
      })
      .catch((e) => setError(String(e.message ?? e)));
  };

  const setSection = (key: keyof SettingsData['sections'], v: boolean) => {
    if (!sections) return;
    const next = { ...sections, [key]: v };
    setSections(next);
    persist({ sections: next });
  };

  const setShufflePref = (patch: Partial<SettingsData['shuffle']>) => {
    if (!shuffle) return;
    const next = { ...shuffle, ...patch };
    setShuffle(next);
    persist({ shuffle: next });
  };

  const setEval = (v: boolean) => {
    setEvalOn(v);
    persist({ evaluation_on: v });
  };

  const doScan = () => {
    setScanning(true);
    setScanErr(null);
    scanLibrary(libRoot.trim())
      .then((s) => {
        setScan(s);
        setScanning(false);
      })
      .catch((e) => {
        setScanErr(String(e.message ?? e));
        setScanning(false);
      });
  };

  const doBrowse = async () => {
    try {
      const chosen = await window.studykit.browseFolder();
      if (!chosen) return;
      setLibRoot(chosen);
      setScanErr(null);
      setScanning(true);
      scanLibrary(chosen)
        .then((s) => setScan(s))
        .catch((e) => setScanErr(String(e.message ?? e)))
        .finally(() => setScanning(false));
    } catch (e) {
      setScanErr(String(e instanceof Error ? e.message : e));
    }
  };

  const togglePath = (path: string) => {
    setSelPaths((prev) => (prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path]));
  };

  const saveLibSelection = () => {
    persist({ library_root: libRoot.trim(), selected_topics: selPaths });
    showNote(`✓ ${selPaths.length} topic(s) selected`);
  };

  const saveApi = () => {
    const body: Partial<SettingsData> = {
      provider_mode: providerMode,
      cli_model: cliModel,
      api: {
        groq: { keys: groqKeys, model: groqModel },
        openrouter: { keys: orKeys, model: orModel },
        custom: { url: custUrl, key: custKey, model: custModel },
      },
    };
    saveSettings(body)
      .then((s) => {
        setSettings(s);
        setGroqKeys([...s.api.groq.keys].concat(Array(KEY_SLOTS).fill('')).slice(0, KEY_SLOTS));
        setOrKeys([...s.api.openrouter.keys].concat(Array(KEY_SLOTS).fill('')).slice(0, KEY_SLOTS));
        setCustKey(s.api.custom.key);
        showNote('✓ Saved');
      })
      .catch((e) => setError(String(e.message ?? e)));
  };

  const setKey = (setter: (v: string[]) => void, keys: string[], i: number, v: string) => {
    const next = [...keys];
    next[i] = v;
    setter(next);
  };

  const clearKey = (setter: (v: string[]) => void, keys: string[], i: number) => {
    const next = [...keys];
    next[i] = '';
    setter(next);
  };

  const addKey = (setter: (v: string[]) => void, keys: string[]) => {
    if (keys.length < KEY_SLOTS) setter([...keys, '']);
  };

  if (loading) {
    return (
      <section className={active ? 'screen active' : 'screen'} id="screen-settings">
        <div className="qhdr">
          <div className="qhdr-l"><span className="q-page-title">Settings</span></div>
        </div>
        <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
          <div className="empty">
            <div className="empty-ico">⏳</div>
            <h3>Loading settings…</h3>
          </div>
        </div>
      </section>
    );
  }

  const tHint =
    tmode === 'off'
      ? 'No time limit. Time spent on each question is still recorded for review.'
      : tmode === 'perQ'
        ? `Per-question countdown of ${tPerQ}s — the quiz auto-advances when time runs out.`
        : `Overall ${tTotal} min across 6 questions → ≈${Math.floor(tTotal * 60 / 6)}s per question; ${tExpiry === 'end' ? 'the quiz ends when the total runs out.' : 'it keeps going — the total is recorded, not enforced.'}`;

  return (
    <section className={active ? 'screen active' : 'screen'} id="screen-settings">
      <div className="qhdr">
        <div className="qhdr-l"><span className="q-page-title">Settings</span></div>
      </div>
      <div className="settings-layout">
        <nav className="settings-nav">
          <button className={pane === 'quiz' ? 'set-nav-btn active' : 'set-nav-btn'} data-set="quiz" onClick={() => setPane('quiz')}>
            <span className="sn-ico">🎯</span>Quiz experience
          </button>
          <button className={pane === 'lib' ? 'set-nav-btn active' : 'set-nav-btn'} data-set="lib" onClick={() => setPane('lib')}>
            <span className="sn-ico">📚</span>Content library
          </button>
          <button className={pane === 'ai' ? 'set-nav-btn active' : 'set-nav-btn'} data-set="ai" onClick={() => setPane('ai')}>
            <span className="sn-ico">🧠</span>AI provider
          </button>
        </nav>
        <div className="settings-content">
          {error && (
            <div className="empty">
              <div className="empty-ico">⚠️</div>
              <h3>Settings error</h3>
              <p>{error}</p>
            </div>
          )}

          {pane === 'quiz' && (
            <div className="set-pane" id="set-pane-quiz">
              <div className="settings-sect">
                <div className="settings-hdr">
                  <div className="settings-hdr-title">Question types</div>
                  <div className="settings-hdr-desc">At least one type must remain enabled.</div>
                </div>
                <div className="settings-body2">
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                    <div className="flex-c g8">
                      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--t2)' }}>Section A — Objective</div>
                      <label className="cb-row">
                        <input type="checkbox" checked={!!sections?.section_a_sim} onChange={(e) => setSection('section_a_sim', e.target.checked)} /> Simulation questions
                      </label>
                      <label className="cb-row">
                        <input type="checkbox" checked={!!sections?.section_a_nonsim} onChange={(e) => setSection('section_a_nonsim', e.target.checked)} /> Non-simulation questions
                      </label>
                    </div>
                    <div className="flex-c g8">
                      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--t2)' }}>Section B — Theory</div>
                      <label className="cb-row">
                        <input type="checkbox" checked={!!sections?.section_b_sim} onChange={(e) => setSection('section_b_sim', e.target.checked)} /> Simulation questions
                      </label>
                      <label className="cb-row">
                        <input type="checkbox" checked={!!sections?.section_b_nonsim} onChange={(e) => setSection('section_b_nonsim', e.target.checked)} /> Non-simulation questions
                      </label>
                    </div>
                  </div>
                  <div style={{ borderTop: '1px solid var(--bd)', paddingTop: 14 }} className="flex-c g8">
                    <label className="cb-row">
                      <input type="checkbox" checked={!!shuffle?.shuffle_enabled} onChange={(e) => setShufflePref({ shuffle_enabled: e.target.checked })} /> Shuffle questions
                    </label>
                    <div style={{ display: shuffle?.shuffle_enabled ? 'flex' : 'none', paddingLeft: 24 }} className="flex-c g8 mt4">
                      <label className="cb-row" style={{ paddingLeft: 22 }}>
                        <input type="radio" name="shuf" checked={!!shuffle?.keep_sim_together} onChange={() => setShufflePref({ keep_sim_together: true })} /> Keep simulation questions together
                      </label>
                      <label className="cb-row" style={{ paddingLeft: 22 }}>
                        <input type="radio" name="shuf" checked={!shuffle?.keep_sim_together} onChange={() => setShufflePref({ keep_sim_together: false })} /> Shuffle all questions
                      </label>
                    </div>
                  </div>
                </div>
              </div>

              <div className="settings-sect">
                <div className="settings-hdr">
                  <div className="settings-hdr-title">Evaluation</div>
                  <div className="settings-hdr-desc">When written answers get scored by AI.</div>
                </div>
                <div className="settings-body2">
                  <div className="set-row">
                    <div className="set-row-lbl">
                      <div className="set-row-title">Default evaluation mode</div>
                      <div className="set-row-sub">Live marks each answer as you go; Off scores everything at the end.</div>
                    </div>
                    <div className="seg">
                      <button className={evalOn ? 'seg-btn on' : 'seg-btn'} onClick={() => setEval(true)}>ON</button>
                      <button className={evalOn ? 'seg-btn' : 'seg-btn on'} onClick={() => setEval(false)}>OFF</button>
                    </div>
                  </div>
                  <div className="set-hint">
                    {evalOn
                      ? 'Evaluation ON: AI scores each written answer immediately. Evaluation OFF: all answers are evaluated together at the end of the quiz.'
                      : 'Evaluation OFF: all answers are evaluated together at the end of the quiz. Evaluation ON: AI scores each written answer immediately.'}
                  </div>
                </div>
              </div>

              <div className="settings-sect">
                <div className="settings-hdr">
                  <div className="settings-hdr-title">Timing</div>
                  <div className="settings-hdr-desc">Auto-advance countdown — per question, or a total test time split across questions.</div>
                </div>
                <div className="settings-body2">
                  <div className="set-row">
                    <div className="set-row-lbl">
                      <div className="set-row-title">Time limit</div>
                      <div className="set-row-sub">A countdown that moves the quiz on when it runs out</div>
                    </div>
                    <div className="seg">
                      <button className={tmode === 'off' ? 'seg-btn on' : 'seg-btn'} onClick={() => setTmode('off')}>Off</button>
                      <button className={tmode === 'perQ' ? 'seg-btn on' : 'seg-btn'} onClick={() => setTmode('perQ')}>Per question</button>
                      <button className={tmode === 'total' ? 'seg-btn on' : 'seg-btn'} onClick={() => setTmode('total')}>Overall test</button>
                    </div>
                  </div>
                  {tmode === 'perQ' && (
                    <div className="set-row">
                      <div className="set-row-lbl">
                        <div className="set-row-title">Seconds per question</div>
                        <div className="set-row-sub">The budget resets on every question</div>
                      </div>
                      <div className="seg">
                        {[30, 60, 90].map((s) => (
                          <button key={s} className={tPerQ === s ? 'seg-btn on' : 'seg-btn'} onClick={() => setTPerQ(s)}>{s}s</button>
                        ))}
                      </div>
                    </div>
                  )}
                  {tmode === 'total' && (
                    <>
                      <div className="set-row">
                        <div className="set-row-lbl">
                          <div className="set-row-title">Total test time</div>
                          <div className="set-row-sub">Split across questions as you go</div>
                        </div>
                        <div className="seg">
                          {[5, 10, 15].map((m) => (
                            <button key={m} className={tTotal === m ? 'seg-btn on' : 'seg-btn'} onClick={() => setTTotal(m)}>{m} min</button>
                          ))}
                        </div>
                      </div>
                      <div className="set-row">
                        <div className="set-row-lbl">
                          <div className="set-row-title">When overall time runs out</div>
                          <div className="set-row-sub">What happens at the deadline</div>
                        </div>
                        <div className="seg">
                          <button className={tExpiry === 'end' ? 'seg-btn on' : 'seg-btn'} onClick={() => setTExpiry('end')}>End quiz</button>
                          <button className={tExpiry === 'continue' ? 'seg-btn on' : 'seg-btn'} onClick={() => setTExpiry('continue')}>Keep going</button>
                        </div>
                      </div>
                    </>
                  )}
                  <div className="set-hint">{tHint}</div>
                </div>
              </div>
            </div>
          )}

          {pane === 'lib' && (
            <div className="set-pane" id="set-pane-lib">
              <div className="settings-sect">
                <div className="settings-hdr">
                  <div className="settings-hdr-title">Learning library</div>
                  <div className="settings-hdr-desc">Point StudyKit at your topic files on disk.</div>
                </div>
                <div className="settings-body2">
                  <div className="sf">
                    <label>Library root path</label>
                    <div className="flex-r g8">
                      <input
                        className="inp"
                        type="text"
                        value={libRoot}
                        onChange={(e) => setLibRoot(e.target.value)}
                        style={{ flex: 1, maxWidth: 380 }}
                      />
                      <button className="btn btn-secondary" onClick={doBrowse}>Browse</button>
                      <button className="btn btn-primary" onClick={doScan}>{scanning ? 'Scanning…' : 'Scan'}</button>
                    </div>
                    {scanErr && <div style={{ color: 'var(--ro-tx)', fontSize: 12.5, marginTop: 8 }}>⚠ {scanErr}</div>}
                    {scan && (
                      <div className="flex-r g6 mt8" style={{ color: 'var(--ja-tx)', fontSize: 12.5, fontWeight: 700 }}>
                        <span>✓</span>
                        <span>Found {scan.valid_count} valid topic(s) across {scan.subject_count} subject(s)</span>
                      </div>
                    )}
                  </div>
                  {scan && (
                    <>
                      <div className="lib-tree">
                        {scan.subjects.map((subj) => (
                          <div key={subj.name}>
                            <div className="tree-subj">▾ {subj.name}</div>
                            {subj.topics.map((t) => (
                              <div className="tree-topic" key={t.folder_path}>
                                <input
                                  type="checkbox"
                                  checked={selPaths.includes(t.folder_path)}
                                  disabled={!t.valid}
                                  onChange={() => togglePath(t.folder_path)}
                                />{' '}
                                {t.name}
                                {!t.valid && <span className="tree-warn">⚠ missing files</span>}
                              </div>
                            ))}
                          </div>
                        ))}
                      </div>
                      <div className="flex-r g10">
                        <button className="btn btn-primary" onClick={saveLibSelection}>Save Selection</button>
                        <span className="saved-note">{note && note.includes('topic') ? note : `${selPaths.length} topic(s) selected`}</span>
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>
          )}

          {pane === 'ai' && (
            <div className="set-pane" id="set-pane-ai">
              <div className="settings-sect">
                <div className="settings-hdr">
                  <div className="settings-hdr-title">Provider mode</div>
                  <div className="settings-hdr-desc">How StudyKit connects to AI — keys stay on your machine.</div>
                </div>
                <div className="settings-body2">
                  <div className="set-row">
                    <div className="set-row-lbl">
                      <div className="set-row-title">Connection</div>
                      <div className="set-row-sub">Direct API keys or the CLI bridge</div>
                    </div>
                    <div className="seg">
                      <button className={providerMode === 'api' ? 'seg-btn on' : 'seg-btn'} onClick={() => { setProviderMode('api'); persist({ provider_mode: 'api' }); }}>API (Direct)</button>
                      <button className={providerMode === 'cli_bridge' ? 'seg-btn on' : 'seg-btn'} onClick={() => { setProviderMode('cli_bridge'); persist({ provider_mode: 'cli_bridge' }); }}>CLI Bridge (opencode)</button>
                    </div>
                  </div>
                  <div style={{ display: providerMode === 'api' ? 'block' : 'none' }}>
                    <div className="flex-c g12">
                      <div className="sf">
                        <label>GROQ Keys <span style={{ fontSize: 11, color: 'var(--t3)' }}>(up to 4)</span></label>
                        {groqKeys.map((k, i) => (
                          <div className="sk-row" key={i}>
                            <input
                              className="inp"
                              type="password"
                              placeholder="gsk_…"
                              value={k}
                              onChange={(e) => setKey(setGroqKeys, groqKeys, i, e.target.value)}
                              style={{ fontFamily: 'monospace', fontSize: 12 }}
                            />
                            <button className="btn btn-ghost btn-sm" onClick={() => clearKey(setGroqKeys, groqKeys, i)}>✕</button>
                          </div>
                        ))}
                        <button className="btn btn-ghost btn-sm" style={{ alignSelf: 'flex-start', marginTop: 4 }} onClick={() => addKey(setGroqKeys, groqKeys)}>+ Add key</button>
                      </div>
                      <div className="sf">
                        <label>GROQ Model</label>
                        <input className="inp" type="text" value={groqModel} onChange={(e) => setGroqModel(e.target.value)} style={{ maxWidth: 340 }} />
                      </div>
                      <div className="sf">
                        <label>OpenRouter Keys <span style={{ fontSize: 11, color: 'var(--t3)' }}>(up to 4)</span></label>
                        {orKeys.map((k, i) => (
                          <div className="sk-row" key={i}>
                            <input
                              className="inp"
                              type="password"
                              placeholder="sk-or-…"
                              value={k}
                              onChange={(e) => setKey(setOrKeys, orKeys, i, e.target.value)}
                              style={{ fontFamily: 'monospace', fontSize: 12 }}
                            />
                            <button className="btn btn-ghost btn-sm" onClick={() => clearKey(setOrKeys, orKeys, i)}>✕</button>
                          </div>
                        ))}
                        <button className="btn btn-ghost btn-sm" style={{ alignSelf: 'flex-start', marginTop: 4 }} onClick={() => addKey(setOrKeys, orKeys)}>+ Add key</button>
                      </div>
                      <div className="sf">
                        <label>OpenRouter Model</label>
                        <input className="inp" type="text" value={orModel} onChange={(e) => setOrModel(e.target.value)} style={{ maxWidth: 340 }} />
                      </div>
                    </div>
                  </div>
                  <div style={{ display: providerMode === 'cli_bridge' ? 'block' : 'none' }}>
                    <div className="sf">
                      <label>Model</label>
                      <input className="inp" type="text" value={cliModel} onChange={(e) => setCliModel(e.target.value)} style={{ maxWidth: 340 }} placeholder="provider/model-name" />
                      <div className="hint">Format: <span className="f-mono">provider/model</span></div>
                    </div>
                  </div>
                  <div className="flex-r g10">
                    <button className="btn btn-primary" onClick={saveApi}>Save API Keys</button>
                    <span className="saved-note" id="api-saved">{note ?? ''}</span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
      {note && pane === 'quiz' && (
        <div style={{ position: 'fixed', bottom: 16, right: 16, zIndex: 100 }}>
          <span className="saved-note" style={{ display: 'flex' }}>{note}</span>
        </div>
      )}
    </section>
  );
}
