import { useI18n } from "../i18n";

export default function SkipLink() {
  const { t } = useI18n();
  return (
    <a className="skip-link" href="#main-content">
      {t("skip.main")}
    </a>
  );
}
