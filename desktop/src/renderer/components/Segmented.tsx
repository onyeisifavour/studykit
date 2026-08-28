interface Option {
  value: string;
  label: string;
}

interface Props {
  options: Option[];
  value: string;
  onChange: (value: string) => void;
  full?: boolean;
}

export default function Segmented({ options, value, onChange, full }: Props) {
  return (
    <div className="seg" style={full ? { width: '100%' } : undefined}>
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          className={value === opt.value ? 'seg-btn on w100' : 'seg-btn w100'}
          style={{ flex: 1 }}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
