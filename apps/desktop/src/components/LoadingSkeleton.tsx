import { useI18n } from "../i18n";

interface Props {
  rows?: number;
}

export default function LoadingSkeleton({ rows = 5 }: Props) {
  const { locale } = useI18n();
  return (
    <ul className="entry-list skeleton-list" aria-busy="true" aria-label={locale === "zh" ? "正在加载账号" : "Loading vault entries"}>
      {Array.from({ length: rows }, (_, i) => (
        <li className="entry-row skeleton-row" key={i}>
          <div className="skeleton-block skeleton-title" />
          <div className="skeleton-block skeleton-meta" />
        </li>
      ))}
    </ul>
  );
}
