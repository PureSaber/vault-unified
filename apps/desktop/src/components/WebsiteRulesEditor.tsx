import { useEffect, useRef, useState } from "react";
import { api, type WebsiteRules } from "../api/client";
import { useI18n } from "../i18n";

export function normalizedWebsiteRules(value?: Partial<WebsiteRules>): WebsiteRules {
  return { match: value?.match || "exact", additional_urls: value?.additional_urls || [], excluded_urls: value?.excluded_urls || [] };
}
export function websiteRulesText(value: WebsiteRules | undefined, zh: boolean): string {
  const rules = normalizedWebsiteRules(value);
  return [rules.match === "exact" ? (zh ? "精确主机" : "Exact host") : (zh ? "同基础域名" : "Same base domain"),
    `${zh ? "其他网址" : "Other websites"}: ${rules.additional_urls.join(", ") || "—"}`,
    `${zh ? "排除网址" : "Excluded websites"}: ${rules.excluded_urls.join(", ") || "—"}`].join("\n");
}

export default function WebsiteRulesEditor({ primaryUrl, value, onChange }: { primaryUrl: string; value: WebsiteRules; onChange: (value: WebsiteRules) => void }) {
  const { locale } = useI18n();
  const zh = locale === "zh";
  const [testUrl, setTestUrl] = useState("");
  const [result, setResult] = useState<"yes" | "no" | "invalid" | "error" | null>(null);
  const [busy, setBusy] = useState(false);
  const sequence = useRef(0);
  useEffect(() => { ++sequence.current; setResult(null); setBusy(false); }, [primaryUrl, value, testUrl]);
  useEffect(() => () => { ++sequence.current; }, []);
  async function test() {
    const stamp = ++sequence.current;
    setBusy(true); setResult(null);
    try {
      const answer = await api.testWebsiteMatch(primaryUrl, value, testUrl);
      if (stamp === sequence.current) setResult(answer.valid ? (answer.matches ? "yes" : "no") : "invalid");
    } catch { if (stamp === sequence.current) setResult("error"); }
    finally { if (stamp === sequence.current) setBusy(false); }
  }
  return <section className="settings-section" aria-labelledby="website-rules-heading">
    <h3 className="section-title" id="website-rules-heading">{zh ? "网站匹配规则" : "Website matching rules"}</h3>
    <p className="field-hint">{zh ? "应用于上方的网站地址和其他网址。路径不参与匹配；协议和端口必须相同。" : "Applies to the main website and other URLs. Paths are ignored; scheme and port must match."}</p>
    <div className="field"><label className="field-label" htmlFor="website-match-mode">{zh ? "匹配方式" : "Matching mode"}</label><select id="website-match-mode" value={value.match} onChange={event => onChange({ ...value, match: event.target.value as WebsiteRules["match"] })}><option value="exact">{zh ? "精确主机（默认）" : "Exact host (default)"}</option><option value="base_domain">{zh ? "同基础域名及其子域" : "Same base domain and subdomains"}</option></select></div>
    {value.match === "base_domain" && <p className="field-hint">{zh ? "将允许同基础域名的所有子域匹配。公共托管服务上的不同用户站点仍分开；本机地址请使用精确匹配。" : "All subdomains of the same base domain can match. Separate users on public hosting services stay separate; use exact matching for local addresses."}</p>}
    {(["additional_urls", "excluded_urls"] as const).map(field => <div key={field} className="website-rules-list">
      <h4>{field === "additional_urls" ? (zh ? "其他网址" : "Other websites") : (zh ? "排除网址（精确主机）" : "Excluded websites (exact host)")}</h4>
      {value[field].map((url, index) => {
        const label = `${field === "additional_urls" ? (zh ? "其他网址" : "Other website") : (zh ? "排除网址" : "Excluded website")} ${index + 1}`;
        return <div className="field" key={index}><label className="field-label" htmlFor={`${field}-${index}`}>{label}</label><div className="input-with-action"><input id={`${field}-${index}`} type="url" required maxLength={2048} value={url} placeholder="https://" onChange={event => onChange({ ...value, [field]: value[field].map((item, position) => position === index ? event.target.value : item) })} /><button type="button" className="secondary" aria-label={`${zh ? "移除" : "Remove"} ${label}`} onClick={() => onChange({ ...value, [field]: value[field].filter((_, position) => position !== index) })}>{zh ? "移除" : "Remove"}</button></div></div>;
      })}
      <button type="button" className="secondary" disabled={value[field].length >= 20} onClick={() => onChange({ ...value, [field]: [...value[field], ""] })}>{field === "additional_urls" ? (zh ? "添加其他网址" : "Add another website") : (zh ? "添加排除网址" : "Add excluded website")}</button>
    </div>)}
    <div className="field"><label className="field-label" htmlFor="website-test-url">{zh ? "测试网址" : "Test website"}</label><div className="input-with-action"><input id="website-test-url" type="text" inputMode="url" maxLength={2048} value={testUrl} placeholder="https://" onChange={event => setTestUrl(event.target.value)} /><button type="button" className="secondary" disabled={!testUrl || busy} onClick={() => void test()}>{zh ? "测试匹配" : "Test match"}</button></div></div>
    {result && <p role="status">{{ yes: zh ? "该网址会匹配此账号。" : "This website matches the account.", no: zh ? "该网址不会匹配此账号。" : "This website does not match the account.", invalid: zh ? "请检查网址；基础域匹配需要有效的注册域名。" : "Check the URLs; base matching needs a valid registrable domain.", error: zh ? "测试失败，请重试。" : "Could not test. Try again." }[result]}</p>}
  </section>;
}
