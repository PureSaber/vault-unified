import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type Integration,
  type IntegrationTestResult,
  type SyncPrefs,
  type SyncPreview,
} from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "./Toast";
import ConfirmDialog from "./ConfirmDialog";
import PathPicker from "./PathPicker";

const copy = {
  zh: {
    title: "可选的密码服务",
    hint: "不连接也可以使用。选择一个服务后，再按步骤完成设置。",
    loading: "加载连接…",
    notSet: "未设置",
    readyToEnable: "待确认启用",
    enabled: "已启用",
    select: "设置此连接",
    change: "继续设置",
    close: "收起",
    steps: ["检查安装", "配置", "测试", "首次导入预览", "确认启用"],
    toolReady: "已找到官方连接工具",
    toolMissing: "缺少官方连接工具。请先按该服务的官方说明安装。",
    save: "保存配置",
    saving: "正在保存…",
    test: "测试连接",
    testing: "正在测试…",
    preview: "预览首次导入",
    previewing: "正在生成预览…",
    enable: "确认启用连接",
    enabling: "正在启用…",
    clear: "清除连接",
    clearTitle: "清除这个连接？",
    clearMessage: "将清除这台设备保存的连接配置。保险库中的密码不会被删除。",
    stored: "已安全保存；留空则保持不变",
    required: "必填",
    saved: "连接配置已保存",
    cleared: "连接配置已清除",
    enabledDone: "连接已启用。请在同步详情中重新预览并确认首次导入。",
    previewSummary: "只读预览",
    noChanges: "没有需要导入的条目。",
    technical: "连接高级设置",
    hideTechnical: "隐藏连接高级设置",
    technicalSource: "配置来源",
    advancedSaved: "高级连接设置已保存",
    defaultLocation: "默认同步位置",
    thisDevice: "这台设备",
    conflictHandling: "两处修改时",
    askEveryTime: "每次让我选择",
    followDefault: "使用默认同步位置",
    autoPush: "保存密码后在后台同步",
    autoPull: "检查连接时获取更新",
  },
  en: {
    title: "Optional password services",
    hint: "You can use the app without a connection. Choose one service, then follow the setup steps.",
    loading: "Loading connections…",
    notSet: "Not set up",
    readyToEnable: "Ready to enable",
    enabled: "Enabled",
    select: "Set up this connection",
    change: "Continue setup",
    close: "Collapse",
    steps: ["Check installation", "Configure", "Test", "Preview first import", "Confirm enable"],
    toolReady: "Official connection tool found",
    toolMissing: "The official connection tool is missing. Install it using the service's official instructions.",
    save: "Save configuration",
    saving: "Saving…",
    test: "Test connection",
    testing: "Testing…",
    preview: "Preview first import",
    previewing: "Building preview…",
    enable: "Confirm and enable connection",
    enabling: "Enabling…",
    clear: "Clear connection",
    clearTitle: "Clear this connection?",
    clearMessage: "This clears connection settings saved on this device. Passwords in the vault are not deleted.",
    stored: "Stored securely; leave blank to keep it",
    required: "required",
    saved: "Connection configuration saved",
    cleared: "Connection configuration cleared",
    enabledDone: "Connection enabled. Create a fresh preview in sync details before confirming the first import.",
    previewSummary: "Read-only preview",
    noChanges: "No entries need to be imported.",
    technical: "Connection advanced settings",
    hideTechnical: "Hide connection advanced settings",
    technicalSource: "Configuration source",
    advancedSaved: "Advanced connection settings saved",
    defaultLocation: "Default sync location",
    thisDevice: "This device",
    conflictHandling: "When both locations changed",
    askEveryTime: "Ask me each time",
    followDefault: "Use the default sync location",
    autoPush: "Sync in the background after saving a password",
    autoPull: "Check for updates when reviewing connections",
  },
} as const;

function initialDrafts(items: Integration[]) {
  return Object.fromEntries(items.map((item) => [
    item.source,
    Object.fromEntries(item.fields.map((field) => [field.key, field.secret ? "" : field.value])),
  ]));
}

function enabledSources(prefs: SyncPrefs, items: Integration[]): string[] {
  if (prefs.enabled_sources == null) {
    return items.filter((item) => item.configured).map((item) => item.source);
  }
  return prefs.enabled_sources;
}

export default function IntegrationManager() {
  const { locale } = useI18n();
  const text = copy[locale];
  const { showToast } = useToast();
  const [items, setItems] = useState<Integration[]>([]);
  const [prefs, setPrefs] = useState<SyncPrefs | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Record<string, string>>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [tests, setTests] = useState<Record<string, IntegrationTestResult>>({});
  const [preview, setPreview] = useState<SyncPreview | null>(null);
  const [showSelectedTechnical, setShowSelectedTechnical] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [clearSource, setClearSource] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [connections, syncPrefs] = await Promise.all([api.integrations(), api.getPrefs()]);
      setItems(connections);
      setDrafts(initialDrafts(connections));
      setPrefs(syncPrefs);
    } catch (loadError) {
      setError(String(loadError).replace(/^Error:\s*/, ""));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const bySource = useMemo(
    () => Object.fromEntries(items.map((item) => [item.source, item])),
    [items],
  );
  const selectedItem = selected ? bySource[selected] : undefined;
  const enabled = new Set(prefs ? enabledSources(prefs, items) : []);

  function updateDraft(source: string, key: string, value: string) {
    setDrafts((previous) => ({
      ...previous,
      [source]: { ...(previous[source] || {}), [key]: value },
    }));
  }

  function replaceItem(updated: Integration) {
    setItems((previous) => previous.map((item) => item.source === updated.source ? updated : item));
    setDrafts((previous) => ({
      ...previous,
      [updated.source]: Object.fromEntries(
        updated.fields.map((field) => [field.key, field.secret ? "" : field.value]),
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
      replaceItem(await api.saveIntegration(source, values));
      setTests((previous) => {
        const next = { ...previous };
        delete next[source];
        return next;
      });
      setPreview(null);
      showToast(text.saved);
    } catch (saveError) {
      const message = String(saveError).replace(/^Error:\s*/, "");
      setError(message);
      showToast(message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function testConnection(source: string) {
    setBusy(`test:${source}`);
    setError("");
    try {
      const result = await api.testIntegration(source);
      setTests((previous) => ({ ...previous, [source]: result }));
      setPreview(null);
      showToast(result.message, result.available ? "success" : "error");
    } catch (testError) {
      const message = String(testError).replace(/^Error:\s*/, "");
      setError(message);
      showToast(message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function previewImport(source: string) {
    setBusy(`preview:${source}`);
    setError("");
    try {
      setPreview(await api.previewSync(true, false, [source]));
    } catch (previewError) {
      const message = String(previewError).replace(/^Error:\s*/, "");
      setError(message);
      showToast(message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function enableConnection(source: string) {
    if (!prefs || !preview) return;
    setBusy(`enable:${source}`);
    try {
      const nextEnabled = Array.from(new Set([...enabledSources(prefs, items), source]));
      const saved = await api.savePrefs({ ...prefs, enabled_sources: nextEnabled });
      setPrefs(saved);
      setPreview(null);
      showToast(text.enabledDone);
    } catch (enableError) {
      const message = String(enableError).replace(/^Error:\s*/, "");
      setError(message);
      showToast(message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function clearConnection() {
    if (!clearSource) return;
    const source = clearSource;
    setClearSource(null);
    setBusy(`clear:${source}`);
    try {
      replaceItem(await api.clearIntegration(source));
      setPreview(null);
      setTests((previous) => {
        const next = { ...previous };
        delete next[source];
        return next;
      });
      showToast(text.cleared);
    } catch (clearError) {
      const message = String(clearError).replace(/^Error:\s*/, "");
      setError(message);
      showToast(message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function saveAdvanced() {
    if (!prefs) return;
    setBusy("advanced");
    try {
      setPrefs(await api.savePrefs(prefs));
      showToast(text.advancedSaved);
    } catch (advancedError) {
      const message = String(advancedError).replace(/^Error:\s*/, "");
      setError(message);
      showToast(message, "error");
    } finally {
      setBusy(null);
    }
  }

  function toggleEnabled(source: string, checked: boolean) {
    if (!prefs) return;
    const next = new Set(enabledSources(prefs, items));
    if (checked) next.add(source);
    else next.delete(source);
    setPrefs({
      ...prefs,
      enabled_sources: Array.from(next),
      primary: prefs.primary !== "local" && !next.has(prefs.primary) ? "local" : prefs.primary,
    });
  }

  return (
    <section className="settings-section" aria-labelledby="integration-heading">
      <ConfirmDialog
        open={clearSource !== null}
        title={text.clearTitle}
        message={text.clearMessage}
        confirmLabel={text.clear}
        variant="danger"
        onConfirm={clearConnection}
        onCancel={() => setClearSource(null)}
      />
      <h3 id="integration-heading" className="section-title">{text.title}</h3>
      <p className="field-hint">{text.hint}</p>

      {loading ? (
        <div className="loading-state">{text.loading}</div>
      ) : (
        <div className="connection-card-grid">
          {items.map((item) => {
            const isEnabled = enabled.has(item.source);
            const status = isEnabled ? text.enabled : item.configured ? text.readyToEnable : text.notSet;
            return (
              <article className={`connection-card${selected === item.source ? " selected" : ""}`} key={item.source}>
                <h4>{item.label}</h4>
                <p>{status}</p>
                <button
                  type="button"
                  className={selected === item.source ? "secondary" : "primary"}
                  aria-pressed={selected === item.source}
                  onClick={() => {
                    setSelected(selected === item.source ? null : item.source);
                    setPreview(null);
                    setShowSelectedTechnical(false);
                  }}
                >
                  {selected === item.source ? text.close : item.configured ? text.change : text.select}
                </button>
              </article>
            );
          })}
        </div>
      )}

      {selectedItem && (
        <section className="connection-wizard" aria-labelledby="connection-wizard-heading">
          <h4 id="connection-wizard-heading">{selectedItem.label}</h4>
          <ol className="connection-steps">
            {text.steps.map((step, index) => <li key={step}><span>{index + 1}</span>{step}</li>)}
          </ol>

          <div className={selectedItem.cli_installed ? "success" : "context-notice context-notice-warning"} role="status">
            {selectedItem.cli_installed ? text.toolReady : text.toolMissing}
          </div>

          {selectedItem.fields.map((field) => {
            const pathMode = field.key === "database_path"
              ? "file"
              : field.key.endsWith("_path")
                ? "directory"
                : null;
            if (pathMode) {
              return (
                <PathPicker
                  key={field.key}
                  id={`${selectedItem.source}-${field.key}`}
                  label={`${field.label} ${field.required ? `(${text.required})` : ""}`.trim()}
                  mode={pathMode}
                  value={drafts[selectedItem.source]?.[field.key] ?? ""}
                  onChange={(value) => updateDraft(selectedItem.source, field.key, value)}
                  extensions={field.key === "database_path" ? ["kdbx"] : undefined}
                  required={field.required}
                  hint={showSelectedTechnical && field.origin ? `${text.technicalSource}: ${field.origin}` : undefined}
                />
              );
            }
            return (
              <div className="field" key={field.key}>
                <label className="field-label" htmlFor={`${selectedItem.source}-${field.key}`}>
                  {field.label} {field.required ? `(${text.required})` : ""}
                </label>
                <input
                  id={`${selectedItem.source}-${field.key}`}
                  type={field.secret ? "password" : "text"}
                  value={drafts[selectedItem.source]?.[field.key] ?? ""}
                  onChange={(event) => updateDraft(selectedItem.source, field.key, event.target.value)}
                  placeholder={field.secret && field.present ? text.stored : ""}
                  autoComplete="off"
                />
                {showSelectedTechnical && field.origin && (
                  <p className="field-hint">{text.technicalSource}: {field.origin}</p>
                )}
              </div>
            );
          })}

          <div className="button-row">
            <button type="button" className="secondary" disabled={busy !== null} onClick={() => save(selectedItem.source)}>
              {busy === `save:${selectedItem.source}` ? text.saving : text.save}
            </button>
            <button type="button" className="secondary" disabled={busy !== null} onClick={() => testConnection(selectedItem.source)}>
              {busy === `test:${selectedItem.source}` ? text.testing : text.test}
            </button>
            <button
              type="button"
              className="primary"
              disabled={busy !== null || (!tests[selectedItem.source]?.available && !enabled.has(selectedItem.source))}
              onClick={() => previewImport(selectedItem.source)}
            >
              {busy === `preview:${selectedItem.source}` ? text.previewing : text.preview}
            </button>
          </div>

          {tests[selectedItem.source] && (
            <div className={tests[selectedItem.source].available ? "success" : "error"} role="status">
              {tests[selectedItem.source].message}
            </div>
          )}

          {preview && preview.sources.includes(selectedItem.source) && (
            <div className="connection-import-preview" role="status">
              <strong>{text.previewSummary}</strong>
              {preview.operations.length === 0 ? (
                <p>{text.noChanges}</p>
              ) : (
                <ul>
                  {preview.operations.map((operation) => (
                    <li key={operation.operation_id}>{operation.title || operation.source_label}: {text.steps[3]}</li>
                  ))}
                </ul>
              )}
              {!enabled.has(selectedItem.source) && (
                <button type="button" className="primary" disabled={busy !== null} onClick={() => enableConnection(selectedItem.source)}>
                  {busy === `enable:${selectedItem.source}` ? text.enabling : text.enable}
                </button>
              )}
            </div>
          )}

          <div className="button-row">
            <button type="button" className="ghost" onClick={() => setShowSelectedTechnical((value) => !value)} aria-expanded={showSelectedTechnical}>
              {showSelectedTechnical ? text.hideTechnical : text.technical}
            </button>
            {selectedItem.configured && (
              <button type="button" className="danger" disabled={busy !== null} onClick={() => setClearSource(selectedItem.source)}>
                {text.clear}
              </button>
            )}
          </div>
          {showSelectedTechnical && (
            <div className="result-panel">
              <div>Source ID: {selectedItem.source}</div>
              <div>CLI: {selectedItem.cli_installed ? "available" : "missing"}</div>
            </div>
          )}
        </section>
      )}

      <button type="button" className="ghost" onClick={() => setShowAdvanced((value) => !value)} aria-expanded={showAdvanced}>
        {showAdvanced ? text.hideTechnical : text.technical}
      </button>
      {showAdvanced && prefs && (
        <section className="connection-advanced" aria-label={text.technical}>
          {items.map((item) => (
            <label className="checkbox-field" key={`enabled-${item.source}`}>
              <input type="checkbox" checked={enabled.has(item.source)} onChange={(event) => toggleEnabled(item.source, event.target.checked)} />
              <span>{item.label}</span>
            </label>
          ))}
          <div className="field">
            <label className="field-label" htmlFor="connection-primary">{text.defaultLocation}</label>
            <select id="connection-primary" value={prefs.primary} onChange={(event) => setPrefs({ ...prefs, primary: event.target.value })}>
              <option value="local">{text.thisDevice}</option>
              {items.filter((item) => enabled.has(item.source)).map((item) => <option value={item.source} key={item.source}>{item.label}</option>)}
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="connection-conflict">{text.conflictHandling}</label>
            <select id="connection-conflict" value={prefs.conflict_default} onChange={(event) => setPrefs({ ...prefs, conflict_default: event.target.value })}>
              <option value="manual">{text.askEveryTime}</option>
              <option value="primary">{text.followDefault}</option>
            </select>
          </div>
          <label className="checkbox-field">
            <input type="checkbox" checked={prefs.auto_push_on_edit} onChange={(event) => setPrefs({ ...prefs, auto_push_on_edit: event.target.checked })} />
            <span>{text.autoPush}</span>
          </label>
          <label className="checkbox-field">
            <input type="checkbox" checked={prefs.auto_pull_on_sync} onChange={(event) => setPrefs({ ...prefs, auto_pull_on_sync: event.target.checked })} />
            <span>{text.autoPull}</span>
          </label>
          <button type="button" className="secondary" disabled={busy !== null} onClick={saveAdvanced}>{text.save}</button>
        </section>
      )}

      {error && <div className="error" role="alert">{error}</div>}
    </section>
  );
}
