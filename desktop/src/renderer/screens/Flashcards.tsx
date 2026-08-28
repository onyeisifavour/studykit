import { useEffect, useState } from 'react';
import { getDeck, getDecks } from '../api';
import type { DeckDetail, DeckSummary } from '../types';

interface Props {
  active: boolean;
}

export default function Flashcards({ active }: Props) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [quizDecks, setQuizDecks] = useState<DeckSummary[]>([]);
  const [libDecks, setLibDecks] = useState<DeckSummary[]>([]);
  const [view, setView] = useState<'list' | 'study' | 'complete'>('list');
  const [deck, setDeck] = useState<DeckDetail | null>(null);
  const [cur, setCur] = useState(0);
  const [got, setGot] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [opening, setOpening] = useState(false);

  const load = () => {
    setLoading(true);
    setError(null);
    getDecks()
      .then((d) => {
        setQuizDecks(d.quiz_decks);
        setLibDecks(d.library_decks);
        setLoading(false);
      })
      .catch((e) => {
        setError(String(e.message ?? e));
        setLoading(false);
      });
  };

  useEffect(load, []);

  const openDeck = (id: string) => {
    setOpening(true);
    setError(null);
    getDeck(id)
      .then((d) => {
        setDeck(d.deck);
        setCur(0);
        setGot(0);
        setFlipped(false);
        setView('study');
        setOpening(false);
      })
      .catch((e) => {
        setError(String(e.message ?? e));
        setOpening(false);
      });
  };

  const flip = () => {
    if (flipped || !deck) return;
    setFlipped(true);
  };

  const rate = (understood: boolean) => {
    if (!deck) return;
    const nextGot = understood ? got + 1 : got;
    const nextCur = cur + 1;
    if (nextCur >= deck.cards.length) {
      setGot(nextGot);
      setView('complete');
    } else {
      setGot(nextGot);
      setCur(nextCur);
      setFlipped(false);
    }
  };

  const back = () => {
    setView('list');
    setDeck(null);
  };

  const restart = () => {
    setCur(0);
    setGot(0);
    setFlipped(false);
    setView('study');
  };

  const card = deck ? deck.cards[cur] : null;
  const allEmpty = !loading && !error && quizDecks.length === 0 && libDecks.length === 0;

  const deckCard = (d: DeckSummary, onOpen: () => void) => (
    <div className="deck-card" key={d.id} onClick={onOpen}>
      <div className="deck-src">{d.source === 'quiz' ? 'Quiz' : 'Library'}</div>
      <div className="deck-title">{d.title}</div>
      <div className="deck-meta">{d.subject || ''}{d.subject ? ' · ' : ''}{d.size} card{d.size === 1 ? '' : 's'}</div>
    </div>
  );

  return (
    <section className={active ? 'screen active' : 'screen'} id="screen-flashcards">
      {view === 'list' && (
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
          <div className="qhdr">
            <div className="qhdr-l"><span className="q-page-title">Flashcards</span></div>
          </div>
          <div className="deck-area">
            {loading ? (
              <div className="empty">
                <div className="empty-ico">⏳</div>
                <h3>Loading your decks…</h3>
              </div>
            ) : error ? (
              <div className="empty">
                <div className="empty-ico">⚠️</div>
                <h3>Couldn't load decks</h3>
                <p>{error}</p>
                <button className="btn btn-secondary" onClick={load}>Try again</button>
              </div>
            ) : allEmpty ? (
              <div className="empty">
                <div className="empty-ico">🃏</div>
                <h3>No decks yet</h3>
                <p>Missed quiz questions and library topics will appear here.</p>
              </div>
            ) : (
              <>
                {quizDecks.length > 0 && (
                  <div>
                    <div className="deck-section-lbl">From your quizzes</div>
                    <div className="deck-grid">
                      {quizDecks.map((d) => deckCard(d, () => openDeck(d.id)))}
                    </div>
                  </div>
                )}
                {libDecks.length > 0 && (
                  <div>
                    <div className="deck-section-lbl">From your library</div>
                    <div className="deck-grid">
                      {libDecks.map((d) => deckCard(d, () => openDeck(d.id)))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {view === 'study' && deck && (
        <div className="fc-study active">
          <div className="fc-study-hdr">
            <button className="btn btn-ghost btn-sm" onClick={back}>← All Decks</button>
            <div style={{ fontSize: 14, fontWeight: 800 }}>{deck.title}</div>
            <div style={{ fontSize: 12.5, color: 'var(--t2)' }}>Card {cur + 1} / {deck.cards.length} · Got it: {got}</div>
          </div>
          <div className="fc-study-body">
            {card ? (
              <>
                <div className="fc-scene">
                  <div className={flipped ? 'fc-card flipped' : 'fc-card'} onClick={flip}>
                    <div className="fc-face fc-front">
                      <div className="fc-face-hint">Question — click to reveal answer</div>
                      <div className="fc-face-text">{card.front}</div>
                    </div>
                    <div className="fc-face fc-back">
                      <div className="fc-face-hint" style={{ color: 'var(--fc)' }}>Answer</div>
                      <div className="fc-face-text">{card.back}</div>
                    </div>
                  </div>
                </div>
                <div className="fc-rating" style={{ display: flipped ? 'flex' : 'none' }}>
                  <button className="btn btn-secondary" onClick={() => rate(false)}>↻ Still learning</button>
                  <button className="btn btn-jade" onClick={() => rate(true)}>✓ Got it</button>
                </div>
              </>
            ) : (
              <div className="empty">
                <div className="empty-ico">🃏</div>
                <h3>Deck is empty</h3>
                <p>No cards were found in this deck.</p>
              </div>
            )}
          </div>
        </div>
      )}

      {view === 'complete' && deck && (
        <div className="fc-complete" style={{ display: 'flex', flexDirection: 'column' }}>
          <div style={{ fontSize: 48 }}>🎉</div>
          <div className="f-h1">Deck complete!</div>
          <div style={{ fontSize: 14, color: 'var(--t2)' }}>
            {deck.cards.length} cards · {got} got it · {deck.cards.length ? Math.round((got / deck.cards.length) * 100) : 0}%
          </div>
          <div className="flex-r g10 mt8">
            <button className="btn btn-secondary" onClick={restart}>↻ Review again</button>
            <button className="btn btn-ghost" onClick={back}>All Decks</button>
          </div>
        </div>
      )}

      {opening && view === 'list' && (
        <div className="empty">
          <div className="empty-ico">⏳</div>
          <h3>Loading deck…</h3>
        </div>
      )}
    </section>
  );
}
