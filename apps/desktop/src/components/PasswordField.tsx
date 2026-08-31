import { useState } from "react";
import type { ReactNode } from "react";
import { useI18n } from "../i18n";

interface Props {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
  required?: boolean;
  action?: ReactNode;
}

export default function PasswordField({
  id,
  label,
  value,
  onChange,
  hint,
  required,
  action,
}: Props) {
  const { t } = useI18n();
  const [visible, setVisible] = useState(false);

  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>{label}</label>
      <div className="input-with-action">
        <input
          id={id}
          type={visible ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          required={required}
          autoComplete="off"
          spellCheck={false}
        />
        <button
          type="button"
          className="secondary icon-btn"
          onClick={() => setVisible((v) => !v)}
          aria-label={visible ? t("list.hidePassword") : t("list.showPassword")}
          aria-pressed={visible}
        >
          {visible ? t("list.hide") : t("list.show")}
        </button>
        {action}
      </div>
      {hint && <p className="field-hint">{hint}</p>}
    </div>
  );
}
