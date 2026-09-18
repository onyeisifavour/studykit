import { useMemo } from 'react';
import katex from 'katex';

interface Segment {
  kind: 'text' | 'math';
  display: boolean;
  value: string;
}

type Renderer = (tex: string, displayMode: boolean) => string;

/**
 * Split a string on LaTeX math delimiters into text/math segments.
 *
 * Supported delimiters (matching the MATH_NOTATION_SPEC the pipeline uses):
 *   - display:  $$...$$           and  \begin{equation}...\end{equation}
 *   - inline:   $...$
 *
 * The tokenizer walks the string once: it looks for `$$`, `\begin{equation}`
 * and single `$` in priority order so a `$$...$$` span is never captured as
 * a pair of inline dollars.
 */
function tokenize(input: string): Segment[] {
  const segments: Segment[] = [];
  const text: string[] = [];
  let i = 0;
  const n = input.length;

  const flushText = () => {
    if (text.length) {
      segments.push({ kind: 'text', display: false, value: text.join('') });
      text.length = 0;
    }
  };

  const pushMath = (value: string, display: boolean) => {
    flushText();
    if (value.trim()) segments.push({ kind: 'math', display, value });
  };

  while (i < n) {
    const rest = input.slice(i);

    // Display 1: $$...$$
    if (rest.slice(0, 2) === '$$') {
      const end = rest.indexOf('$$', 2);
      if (end !== -1) {
        pushMath(rest.slice(2, end), true);
        i += end + 2;
        continue;
      }
      // Unterminated $$... — treat the double dollars as literal text.
      text.push('$$');
      i += 2;
      continue;
    }

    // Display 2: \begin{equation}...\end{equation}
    if (rest.startsWith('\\begin{equation}')) {
      const endMatch = /\\end\{equation\}/.exec(rest);
      if (endMatch) {
        const content = rest.slice('\\begin{equation}'.length, endMatch.index);
        pushMath(content, true);
        i += endMatch.index + endMatch[0].length;
        continue;
      }
      text.push('\\begin{equation}');
      i += '\\begin{equation}'.length;
      continue;
    }

    // Inline: $...$
    if (rest[0] === '$') {
      const end = rest.indexOf('$', 1);
      if (end > 1) {
        pushMath(rest.slice(1, end), false);
        i += end + 1;
        continue;
      }
      text.push('$');
      i += 1;
      continue;
    }

    text.push(rest[0]);
    i += 1;
  }

  flushText();
  return segments;
}

const fallbackRender: Renderer = (tex, display) => {
  const blockClass = display ? ' rich-math-block' : ' rich-math-inline';
  return `<span class="${blockClass} rich-math-fallback" title="unrenderable math">${escapeHtml(tex)}</span>`;
};

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function renderSegment(seg: Segment): string {
  if (seg.kind === 'text') {
    const escaped = escapeHtml(seg.value);
    // Preserve line breaks in plain text as <br>.
    return escaped.replace(/\n/g, '<br/>');
  }
  try {
    return katex.renderToString(seg.value, {
      displayMode: seg.display,
      throwOnError: false,
      strict: false,
    });
  } catch {
    return fallbackRender(seg.value, seg.display);
  }
}

interface Props {
  text?: string;
}

/** Renders plain text with $…$ / $$…$$ / \begin{equation} LaTeX spans. */
export default function RichText({ text }: Props) {
  const html = useMemo(() => {
    if (!text) return '';
    let out = '';
    for (const seg of tokenize(text)) out += renderSegment(seg);
    return out;
  }, [text]);

  if (!text) return null;
  return <span dangerouslySetInnerHTML={{ __html: html }} />;
}