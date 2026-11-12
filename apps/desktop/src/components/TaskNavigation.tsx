export default function TaskNavigation({ label, items, current, busy, onChange }: {
  label: string;
  items: Array<{ id: string; label: string }>;
  current: string;
  busy?: boolean;
  onChange: (id: string) => void;
}) {
  return <nav className="section-nav task-navigation" aria-label={label}>
    {items.map(item => <button key={item.id} type="button" className="ghost"
      aria-current={item.id === current ? "page" : undefined}
      disabled={busy && item.id !== current}
      onClick={() => onChange(item.id)}>{item.label}</button>)}
  </nav>;
}
