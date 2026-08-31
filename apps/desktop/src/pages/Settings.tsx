import packageMetadata from "../../package.json";
import { useI18n, type Locale } from "../i18n";

export default function Settings() {
  const { t, locale, setLocale } = useI18n();

  return (
    <div className="card">
      <h2>{t("settings.title")}</h2>
      <p className="field-hint">{t("settings.simpleHint")}</p>

      <section className="settings-section" aria-labelledby="locale-heading">
        <h3 id="locale-heading" className="section-title">
          {t("settings.language")}
        </h3>
        <div className="field">
          <label className="field-label" htmlFor="settings-locale">
            {t("lang.label")}
          </label>
          <select
            id="settings-locale"
            value={locale}
            onChange={(event) => setLocale(event.target.value as Locale)}
          >
            <option value="zh">{t("lang.zh")}</option>
            <option value="en">{t("lang.en")}</option>
          </select>
        </div>
      </section>

      <section className="settings-section" aria-labelledby="about-heading">
        <h3 id="about-heading" className="section-title">{t("settings.about")}</h3>
        <dl className="status-grid">
          <div className="status-row">
            <dt>{t("settings.product")}</dt>
            <dd>Vault Unified</dd>
          </div>
          <div className="status-row">
            <dt>{t("settings.version")}</dt>
            <dd>{packageMetadata.version}</dd>
          </div>
          <div className="status-row">
            <dt>{t("settings.platform")}</dt>
            <dd>Windows</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
