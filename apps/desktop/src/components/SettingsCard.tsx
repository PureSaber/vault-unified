import type { ReactNode } from "react";
import { useI18n } from "../i18n";

export default function SettingsCard({ id, title, mode, state, children }: {
  id: string;
  title: string;
  mode?: "immediate" | "submit";
  state?: "saving" | "saved" | "unsaved" | "error";
  children: ReactNode;
}) {
  const { t } = useI18n();
  return <section className="settings-section settings-card" aria-labelledby={id}>
    <div className="settings-card-header">
      <h3 id={id} className="section-title">{title}</h3>
      {mode && <span className="chip">{t(`settingsSave.${mode}`)}</span>}
    </div>
    {children}
    {state && <p className={`settings-save-state settings-save-${state}`} role="status">{t(`settingsSave.${state}`)}</p>}
  </section>;
}
