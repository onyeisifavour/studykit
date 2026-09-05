interface Props {
  active: boolean;
}

export default function Tutor({ active }: Props) {
  return (
    <section className={active ? 'screen active' : 'screen'} id="screen-tutor">
      <div className="qhdr">
        <div className="qhdr-l"><span className="q-page-title">Tutor</span></div>
      </div>
      <div className="tutor-layout">
        <div className="tutor-ql">
          <div className="tutor-ql-top">
            <div className="tutor-ql-hdr">Tutoring on</div>
          </div>
          <div className="empty">
            <div className="empty-ico">💬</div>
            <h3>No quizzes yet</h3>
            <p>Complete a quiz to get questions you can be tutored on.</p>
          </div>
        </div>
        <div className="tutor-main">
          <div className="tutor-chat">
            <div className="empty">
              <div className="empty-ico">💬</div>
              <h3>Select a question to start tutoring</h3>
              <p>Choose from the list to open a dedicated tutoring thread.</p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
