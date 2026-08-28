interface Props {
  label: string;
  tone?: 'violet' | 'amber' | 'jade' | 'neutral' | 'rose';
  pulse?: boolean;
}

export default function StageBadge({ label, tone = 'neutral', pulse }: Props) {
  return <span className={`badge b-${tone}${pulse ? ' b-pulse' : ''}`}>{label}</span>;
}
