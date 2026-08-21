import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type Integration,
  type IntegrationTestResult,
} from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "./Toast";

const copy = {
  zh: {
    title: "外部密码库连接",
    hint: "秘密字段保存到系统凭据管理器；普通路径和服务器设置保存到本机配置文件。.env 仅作为开发兼容回退。",
    loading: "加载连接设置…",
    save: "保存",
    saving: "保存中…",
    test: "测试连接",
    testing: "测试中…",
    clear: "清除连接",
    configured: "已配置",
    incomplete: "配置不完整",
    cliReady: "CLI 已安装",
    cliMissing: "CLI 未安装",
    stored: "已安全保存；留空则保持不变",
    required: "必填",
    origin: "来源",
    saved: "连接设置已保存",
    cleared: "连接设置已清除",
    confirmClear: "清除该来源保存在 Keyring 和本地配置中的全部设置？环境变量不会被修改。",
  },
  en: {
    title: "External password-manager connections",
    hint: "Secret fields are stored in the OS credential manager. Paths and server settings use a local config file. .env remains a development-only fallback.",
    loading: "Loading connection settings…",
    save: "Save",
    saving: "Saving…",
    test: "Test connection",
    testing: "Testing…",
    clear: "Clear connection",
    configured: "Configured",
    incomplete: "Incomplete",
    cliReady: "CLI installed",
    cliMissing: "CLI missing",
    stored: "Stored securely; leave blank to keep it",
    required: "required",
    origin: "source",
    saved: "Connection settings saved",
    cleared: "Connection settings cleared",
    confirmClear: "Clear all Keyring and local configuration for this source? Environment variables are not changed.",
  },
} as const;

function initialDrafts(items: Integration[]) {
  const result: Record<string, Record<string, string>> = {};
  for (const item of items) {
    result[item.source] = {};
    for (const field of item.fields) {
      result[item.source][field.key] = field.secret ? "" : field.value;
    }
  }
  return result;
}

export default function IntegrationManager() {
  const { locale } = useI18n();
  const text = copy[locale];
  const { showToast } = useToast();
  const [items, setItems] = useState<Integration[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Record<string, string>>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [tests, setTests] = useState<Record<string, IntegrationTestResult>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api.integrations();
      setItems(data);
      setDrafts(initialDrafts(data));
    } catch (err) {
      setError(String(err).replace(/^Error:\s*/, ""));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const bySource = useMemo(
    () => Object.fromEntries(items.map((item) => [item.source, item])),
    [items]
  );

  function updateDraft(source: string, key: string, value: string) {
    setDrafts((previous) => ({
      ...previous,
      [source]: {
        ...(previous[source] || {}),
        [key]: value,
      },
    }));
  }

  function replaceItem(updated: Integration) {
    setItems((previous) =>
      previous.map((item) => (item.source === updated.source ? updated : item))
    );
    setDrafts((previous) => ({
      ...previous,
      [updated.source]: Object.fromEntries(
        updated.fields.map((field) => [field.key, field.secret ? "" : field.value])
      ),
    }));
  }

  async function save(source: string) {
    const item = bySource[source];
    if (!item) return;
    setBusy(`save:${source}`);
    setError("");
    try {
      const values: Record<string, string> = {};
      for (const field of item.fields) {
        const value = drafts[source]?.[field.key] ?? "";
        if (!field.secret || value) values[field.key] = value;
      }
      const updated = await api.saveIntegration(source, values);
      replaceItem(updated);
      setTests((previous) => {
        const next = { ...previous };
        delete next[source];
        return next;
      });
      showToast(text.saved);
    } catch (err) {
      const message = String(err).replace(/^Error:\s*/, "");
      setError(message);
      showToast(message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function test(source: string) {
    setBusy(`test:${source}`);
    setError("");
    try {
      const result = await api.testIntegration(source);
      setTests((previous) => ({ ...previous, [source]: result }));
      showToast(result.message, result.available ? "success" : "error");
    } catch (err) {
      const message = String(err).replace(/^Error:\s*/, "");
      setError(message);
      showToast(message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function clear(source: string) {
    if (!window.confirm(text.confirmClear)) return;
    setBusy(`clear:${source}`);
    setError("");
    try {
      const updated = await api.clearIntegration(source);
      replaceItem(updated);
      setTests((previous) => {
        const next = { ...previous };
        delete next[source];
        return next;
      });
      showToast(text.cleared);
    } catch (err) {
      const message = String(err).replace(/^Error:\s*/, "");
      setError(message);
      showToast(message, "error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="settings-section" aria-labelledby="integration-heading">
      <h3 id="integration-heading" className="section-title">
        {text.title}
      </h3>
      <p className="field-hint">{text.hint}</p>

      {loading ? (
        <div className="loading-state">{text.loading}</div>
      ) : (
        items.map((item) => {
          const testResult = tests[item.source];
          return (
            <article className="card" key={item.source} style={{ marginTop: "var(--space-lg)" }}>
              <div className="conflict-header">
                <h4 style={{ margin: 0 }}>{item.label}</h4>
                <div className="entry-chips">
                  <span className="chip">
                    {item.configured ? text.configured : text.incomplete}
                  </span>
                  <span className="chip">
                    {item.cli_installed ? text.cliReady : text.cliMissing}
                  </span>
                </div>
              </div>

              {item.fields.map((field) => (
                <div className="field" key={field.key}>
                  <label className="field-label" htmlFor={`${item.source}-${field.key}`}>
                    {field.label} {field.required ? `(${text.required})` : ""}
                  </label>
                  <input
                    id={`${item.source}-${field.key}`}
                    type={field.secret ? "password" : "text"}
                    value={drafts[item.source]?.[field.key] ?? ""}
                    onChange={(event) =>
                      updateDraft(item.source, field.key, event.target.value)
                    }
                    placeholder={field.secret && field.present ? text.stored : ""}
                    autoComplete="off"
                  />
                  {field.origin && (
                    <p className="field-hint">
                      {text.origin}: {field.origin}
                    </p>
                  )}
                </div>
              ))}

              {testResult && (
                <div className={testResult.available ? "success" : "error"} role="status">
                  {testResult.message}
                </div>
              )}

              <div className="button-row">
                <button
                  type="button"
                  className="primary"
                  disabled={busy !== null}
                  onClick={() => save(item.source)}
                >
                  {busy === `save:${item.source}` ? text.saving : text.save}
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={busy !== null}
                  onClick={() => test(item.source)}
                >
                  {busy === `test:${item.source}` ? text.testing : text.test}
                </button>
                <button
                  type="button"
                  className="danger"
                  disabled={busy !== null}
                  onClick={() => clear(item.source)}
                >
                  {text.clear}
                </button>
              </div>
            </article>
          );
        })
      )}

      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
    </section>
  );
}
