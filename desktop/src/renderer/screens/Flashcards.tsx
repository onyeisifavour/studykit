interface Props {
  active: boolean;
}

export default function Flashcards({ active }: Props) {
  return (
    <section className={active ? 'screen active' : 'screen'} id="screen-flashcards">
      <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
        <div className="qhdr">
          <div className="qhdr-l"><span className="q-page-title">Flashcards</span></div>
        </div>
        <div className="deck-area">
          <div className="empty">
            <div className="empty-ico">🃏</div>
            <h3>No decks yet</h3>
            <p>Missed quiz questions and library topics will appear here.</p>
          </div>
        </div>
      </div>
    </section>
  );
}
