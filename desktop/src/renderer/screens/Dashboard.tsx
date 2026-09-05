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

export default function Dashboard({ onNavigate, active }: Props) {
  return (
    <section className={active ? 'screen active' : 'screen'} id="screen-dashboard">
      <div className="scroll-area">
        <div className="dash-hero">
          <div>
            <div className="dash-hero-greet">{greeting()} 👋</div>
            <div className="dash-hero-stats mt8">
              <strong>—</strong> quizzes · <strong>—</strong> questions answered ·{' '}
              <strong>—</strong>% average
            </div>
          </div>
          <button className="btn btn-primary btn-lg" onClick={() => onNavigate('quiz')}>Start New Quiz →</button>
        </div>

        <div className="dash-grid">
          <div className="card card-p">
            <div className="dash-section-label">Subject mastery</div>
            <div className="c3" style={{ fontSize: 13.5 }}>No quiz data yet — your subjects will appear here.</div>
          </div>

          <div className="card card-p">
            <div className="dash-section-label">Recent activity</div>
            <div className="c3" style={{ fontSize: 13.5 }}>No quizzes taken yet.</div>
          </div>

          <div className="card card-p dash-full">
            <div className="dash-section-label">Needs attention</div>
            <div className="c3" style={{ fontSize: 13.5 }}>Nothing flagged — nice work.</div>
          </div>
        </div>
      </div>
    </section>
  );
}
