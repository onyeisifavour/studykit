import { useState } from 'react';
import Dashboard from './screens/Dashboard';
import Flashcards from './screens/Flashcards';
import History from './screens/History';
import Quiz from './screens/Quiz';
import Settings from './screens/Settings';
import Tutor from './screens/Tutor';

const ICON_PROPS = {
  width: 18,
  height: 18,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const;

const NAV_ITEMS = [
  {
    id: 'dashboard',
    label: 'Dashboard',
    icon: (
      <svg {...ICON_PROPS}>
        <rect x="3" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" />
        <rect x="14" y="14" width="7" height="7" rx="1.5" />
      </svg>
    ),
  },
  {
    id: 'quiz',
    label: 'Quiz',
    icon: (
      <svg {...ICON_PROPS}>
        <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" />
      </svg>
    ),
  },
  {
    id: 'flashcards',
    label: 'Flashcards',
    icon: (
      <svg {...ICON_PROPS}>
        <path d="m12 2-10 5 10 5 10-5-10-5z" />
        <path d="m2 12 10 5 10-5" />
        <path d="m2 17 10 5 10-5" />
      </svg>
    ),
  },
  {
    id: 'history',
    label: 'History',
    icon: (
      <svg {...ICON_PROPS}>
        <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
        <path d="M3 3v5h5" />
        <path d="M12 7v5l3 2" />
      </svg>
    ),
  },
  {
    id: 'tutor',
    label: 'Tutor',
    icon: (
      <svg {...ICON_PROPS}>
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      </svg>
    ),
  },
];

const NAV_BOTTOM = [
  {
    id: 'settings',
    label: 'Settings',
    icon: (
      <svg {...ICON_PROPS}>
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.09a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.09a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.09a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
      </svg>
    ),
  },
];

export default function App() {
  const [screen, setScreen] = useState('dashboard');
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="app-shell">
      <nav className={collapsed ? 'nav-rail collapsed' : 'nav-rail'}>
        <div className="nav-brand">
          <div className="nav-logo">SK</div>
          <span className="nav-brand-name">StudyKit</span>
          <button
            className="nav-collapse-btn"
            title="Toggle sidebar"
            aria-label="Toggle sidebar"
            onClick={() => setCollapsed((c) => !c)}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="m11 17-5-5 5-5" />
              <path d="m18 17-5-5 5-5" />
            </svg>
          </button>
        </div>

        <div className="nav-items">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              className={screen === item.id ? 'nav-item active' : 'nav-item'}
              onClick={() => setScreen(item.id)}
            >
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-label">{item.label}</span>
            </button>
          ))}
        </div>

        <div className="nav-bottom">
          {NAV_BOTTOM.map((item) => (
            <button
              key={item.id}
              className={screen === item.id ? 'nav-item active' : 'nav-item'}
              onClick={() => setScreen(item.id)}
            >
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-label">{item.label}</span>
            </button>
          ))}
          <span className="nav-version">v0.3 — Electron preview</span>
        </div>
      </nav>

      <main className="content-region">
        <Dashboard onNavigate={setScreen} active={screen === 'dashboard'} />
        <Quiz onNavigate={setScreen} active={screen === 'quiz'} />
        <Flashcards active={screen === 'flashcards'} />
        <History onNavigate={setScreen} active={screen === 'history'} />
        <Tutor active={screen === 'tutor'} />
        <Settings active={screen === 'settings'} />
      </main>
    </div>
  );
}
