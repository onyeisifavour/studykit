interface Props {
  icon: string;
  title: string;
  subtitle?: string;
  children?: React.ReactNode;
}

export default function EmptyState({ icon, title, subtitle, children }: Props) {
  return (
    <div className="empty">
      <div className="empty-ico">{icon}</div>
      <h3>{title}</h3>
      {subtitle ? <p>{subtitle}</p> : null}
      {children}
    </div>
  );
}
