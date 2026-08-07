interface Props {
  rows?: number;
}

export default function LoadingSkeleton({ rows = 5 }: Props) {
  return (
    <ul className="entry-list skeleton-list" aria-busy="true" aria-label="Loading vault entries">
      {Array.from({ length: rows }, (_, i) => (
        <li className="entry-row skeleton-row" key={i}>
          <div className="skeleton-block skeleton-title" />
          <div className="skeleton-block skeleton-meta" />
        </li>
      ))}
    </ul>
  );
}
