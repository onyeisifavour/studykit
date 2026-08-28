import { useEffect, useRef } from 'react';

export interface ChatMessage {
  role: 'user' | 'ai';
  text?: string;
  typing?: boolean;
}

interface BubblesProps {
  messages: ChatMessage[];
}

export function ChatBubbles({ messages }: BubblesProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  return (
    <div className="chat-messages" ref={ref}>
      {messages.map((m, i) =>
        m.typing ? (
          <div className="chat-bubble bubble-ai" key={i}>
            <span className="bubble-dots">
              <span />
              <span />
              <span />
            </span>
          </div>
        ) : (
          <div className={m.role === 'user' ? 'chat-bubble bubble-user' : 'chat-bubble bubble-ai'} key={i}>
            {m.text}
          </div>
        ),
      )}
    </div>
  );
}

interface InputProps {
  placeholder?: string;
  onSend: (text: string) => void;
  disabled?: boolean;
  extra?: React.ReactNode;
}

export function ChatInput({ placeholder, onSend, disabled, extra }: InputProps) {
  const ref = useRef<HTMLTextAreaElement>(null);

  const autoGrow = () => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
    el.style.overflowY = el.scrollHeight > 120 ? 'auto' : 'hidden';
  };

  const submit = () => {
    const el = ref.current;
    if (!el) return;
    const text = el.value.trim();
    if (!text) return;
    el.value = '';
    autoGrow();
    onSend(text);
  };

  return (
    <div className="chat-row">
      <textarea
        className="chat-inp"
        placeholder={placeholder ?? 'Type a message…'}
        rows={1}
        ref={ref}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
        onInput={autoGrow}
      />
      <button className="btn btn-secondary" type="button" disabled={disabled} onClick={submit}>
        Send
      </button>
      {extra}
    </div>
  );
}
