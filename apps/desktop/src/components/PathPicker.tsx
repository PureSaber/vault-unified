import { open } from "@tauri-apps/plugin-dialog";
import { useState } from "react";
import { useI18n } from "../i18n";

interface Props {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  mode: "file" | "directory";
  hint?: string;
  placeholder?: string;
  required?: boolean;
  extensions?: string[];
}

export default function PathPicker({
  id,
  label,
  value,
  onChange,
  mode,
  hint,
  placeholder,
  required,
  extensions,
}: Props) {
  const { locale } = useI18n();
  const zh = locale === "zh";
  const [showManual, setShowManual] = useState(false);
  const [error, setError] = useState("");

  async function choosePath() {
    setError("");
    try {
      const selected = await open({
        directory: mode === "directory",
        multiple: false,
        defaultPath: value || undefined,
        filters: mode === "file" && extensions?.length
          ? [{ name: zh ? "支持的文件" : "Supported files", extensions }]
          : undefined,
      });
      if (typeof selected === "string") onChange(selected);
    } catch {
      setShowManual(true);
      setError(zh ? "系统选择器在当前测试环境中不可用，请使用手工输入。" : "The system picker is unavailable in this test environment. Use manual entry.");
    }
  }

  return (
    <div className="field path-picker">
      <span className="field-label" id={`${id}-label`}>{label}</span>
      <div className="path-picker-row">
        <span className={value ? "path-picker-value" : "path-picker-value is-empty"} aria-labelledby={`${id}-label`}>
          {value || placeholder || (zh ? "尚未选择" : "Nothing selected")}
        </span>
        <button type="button" className="secondary" onClick={() => void choosePath()}>
          {mode === "directory" ? (zh ? "选择文件夹" : "Choose folder") : (zh ? "选择文件" : "Choose file")}
        </button>
      </div>
      <button type="button" className="ghost compact-disclosure" onClick={() => setShowManual((current) => !current)} aria-expanded={showManual} aria-controls={`${id}-manual`}>
        {showManual ? (zh ? "隐藏手工输入" : "Hide manual entry") : (zh ? "手工输入路径（高级）" : "Enter path manually (advanced)")}
      </button>
      {showManual && (
        <input
          id={id}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          required={required}
          autoComplete="off"
          aria-labelledby={`${id}-label`}
        />
      )}
      {hint && <p className="field-hint">{hint}</p>}
      {error && <p className="error" role="status">{error}</p>}
    </div>
  );
}
