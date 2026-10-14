import type { GenerationOptions } from "../api/client";
import { useI18n } from "../i18n";

export const defaultGenerationOptions: GenerationOptions = { kind: "password", length: 20, symbols: true, upper: true, lower: true, digits: true, allowed: "", excluded: "", words: 6, separator: "-" };

export default function GeneratorOptions({ value, onChange, historyEnabled }: { value: GenerationOptions; onChange: (value: GenerationOptions) => void; historyEnabled: boolean }) {
  const { locale, t } = useI18n();
  const zh = locale === "zh";
  const patch = (change: Partial<GenerationOptions>) => onChange({ ...value, ...change });
  return <div className="generator-options" id="generator-options">
    {historyEnabled && <div className="field"><label className="field-label" htmlFor="gen-kind">{zh ? "生成方式" : "Generate as"}</label><select id="gen-kind" value={value.kind} onChange={event => patch({ kind: event.target.value as GenerationOptions["kind"] })}><option value="password">{zh ? "随机密码" : "Random password"}</option><option value="passphrase">{zh ? "口令短语" : "Passphrase"}</option></select></div>}
    {value.kind === "password" ? <>
      <div className="field generate-length"><label className="field-label" htmlFor="gen-length">{t("form.genLength")}</label><input id="gen-length" type="number" min={8} max={128} value={value.length} onChange={event => patch({ length: Math.min(128, Math.max(8, Number(event.target.value) || 8)) })} /></div>
      {(historyEnabled ? ["lower", "upper", "digits", "symbols"] as const : ["symbols"] as const).map(key => <label key={key} className="checkbox-field"><input type="checkbox" checked={value[key]} onChange={event => patch({ [key]: event.target.checked })} /><span>{{ lower: zh ? "小写字母" : "Lowercase", upper: zh ? "大写字母" : "Uppercase", digits: zh ? "数字" : "Digits", symbols: t("form.genSymbols") }[key]}</span></label>)}
      {historyEnabled && <><div className="field generator-wide"><label className="field-label" htmlFor="gen-allowed">{zh ? "仅允许这些字符（留空不限）" : "Allowed characters (empty for no restriction)"}</label><input id="gen-allowed" maxLength={128} value={value.allowed} onChange={event => patch({ allowed: event.target.value })} spellCheck={false} autoComplete="off" /></div><div className="field generator-wide"><label className="field-label" htmlFor="gen-excluded">{zh ? "排除这些字符" : "Excluded characters"}</label><input id="gen-excluded" maxLength={128} value={value.excluded} onChange={event => patch({ excluded: event.target.value })} spellCheck={false} autoComplete="off" /></div><p className="field-hint generator-wide">{zh ? "每个启用的字符组至少保留一个字符；总共至少允许 10 个不同字符。" : "Keep characters in every enabled group and at least 10 distinct characters overall."}</p></>}
    </> : <>
      <div className="field"><label className="field-label" htmlFor="gen-words">{zh ? "单词数量" : "Number of words"}</label><input id="gen-words" type="number" min={6} max={12} value={value.words} onChange={event => patch({ words: Math.min(12, Math.max(6, Number(event.target.value) || 6)) })} /></div>
      <div className="field"><label className="field-label" htmlFor="gen-separator">{zh ? "分隔符" : "Separator"}</label><select id="gen-separator" value={value.separator} onChange={event => patch({ separator: event.target.value as GenerationOptions["separator"] })}><option value="-">-</option><option value=" ">{zh ? "空格" : "Space"}</option><option value=".">.</option><option value="_">_</option></select></div>
      <p className="field-hint generator-wide">{zh ? "从本地 EFF 词表的 7,776 个英文单词中独立随机选取。" : "Words are chosen independently from the local EFF list of 7,776 English words."}</p>
    </>}
  </div>;
}
