import { useEffect, useState } from "react";
import {
  api,
  type SyncPreview,
  type SyncSourcePreview,
} from "../api/client";
import { useToast } from "../components/Toast";
import SyncResultSummary, {
  type SyncResultData,
} from "../components/SyncResultSummary";
import LoadingSkeleton from "../components/LoadingSkeleton";
import { useI18n } from "../i18n";

const PULL_SOURCES = [
  "proton_pass",
  "bitwarden",
  "keepassxc",
  "gopass",
] as const;

const copy = {
  zh: {
    hint: "同步分为“只读预览”和“确认执行”两步。预览不会修改本地或远端数据。",
    previewBoth: "预览双向同步",
    previewPush: "预览推送",
    previewPull: "预览拉取",
    previewing: "正在生成预览…",
    plan: "待确认的同步计划",
    expires: "预览有效至",
    pull: "拉取",
    push: "推送",
    remoteTotal: "远端总数",
    add: "新增",
    update: "更新",
    conflict: "冲突",
    unchanged: "不变",
    localOnly: "仅本地变化",
    deleteObserved: "观察到删除",
    create: "创建",
    delete: "删除",
    pending: "结果待核对",
    unavailable: "不可用来源",
    warning: "风险提示",
    confirm: "确认并执行",
    executing: "正在执行…",
    confirmNormal: "确认执行这份同步预览？预览令牌只能使用一次。",
    confirmDestructive:
      "这份计划包含删除操作。当前数据可能被远端删除或远端条目可能被删除。确认继续？",
    previewReady: "同步预览已生成，请核对后确认。",
    stale:
      "预览已失效或数据发生变化。软件没有执行同步，请重新生成预览。",
  },
  en: {
    hint:
      "Sync now has two phases: a read-only preview and an explicit confirmation. Preview never writes local or remote data.",
    previewBoth: "Preview bidirectional sync",
    previewPush: "Preview push",
    previewPull: "Preview pull",
    previewing: "Building preview…",
    plan: "Sync plan awaiting confirmation",
    expires: "Preview expires",
    pull: "Pull",
    push: "Push",
    remoteTotal: "Remote total",
    add: "Add",
    update: "Update",
    conflict: "Conflicts",
    unchanged: "Unchanged",
    localOnly: "Local-only changes",
    deleteObserved: "Observed deletions",
    create: "Create",
    delete: "Delete",
    pending: "Unknown outcome",
    unavailable: "Unavailable sources",
    warning: "Warnings",
    confirm: "Confirm and execute",
    executing: "Executing…",
    confirmNormal:
      "Execute this reviewed sync plan? The preview token can be used only once.",
    confirmDestructive:
      "This plan includes deletions. Local data may reflect remote deletion or remote entries may be deleted. Continue?",
    previewReady: "Sync preview is ready. Review it before confirming.",
    stale:
      "The preview expired or state changed. Nothing was executed; create a new preview.",
  },
} as const;

interface Props {
  onOpenConflicts?: () => void;
  onSyncDone?: () => void;
}

export default function SyncPanel({
  onOpenConflicts,
  onSyncDone,
}: Props) {
  const { t, locale } = useI18n();
  const text = copy[locale];
  const { showToast } = useToast();
  const [status, setStatus] = useState<Record<string, string>>({});
  const [statusLoading, setStatusLoading] = useState(true);
  const [result, setResult] = useState<SyncResultData | null>(null);
  const [preview, setPreview] = useState<SyncPreview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<"preview" | "execute" | null>(null);

  async function loadStatus() {
    try {
      setStatusLoading(true);
      const res = await api.status();
      setStatus(res.components);
      setError("");
    } catch (err) {
      setError(String(err).replace(/^Error:\s*/, ""));
    } finally {
      setStatusLoading(false);
    }
  }

  useEffect(() => {
    loadStatus();
  }, []);

  const conflictCount = result?.conflicts?.length ?? 0;
  const anyBusy = busy !== null;

  async function buildPreview(
    includePull: boolean,
    includePush: boolean,
    sources?: string[]
  ) {
    setError("");
    setBusy("preview");
    setResult(null);
    try {
      const plan = await api.previewSync(
        includePull,
        includePush,
        sources
      );
      setPreview(plan);
      showToast(text.previewReady);
    } catch (err) {
      const msg = String(err).replace(/^Error:\s*/, "");
      setPreview(null);
      setError(msg);
      showToast(msg, "error");
    } finally {
      setBusy(null);
    }
  }

  async function executePreview() {
    if (!preview) return;
    const prompt =
      preview.destructive_count > 0
        ? text.confirmDestructive
        : text.confirmNormal;
    if (!window.confirm(prompt)) return;

    setError("");
    setBusy("execute");
    try {
      const res = (await api.executeSync(
        preview.preview_token
      )) as SyncResultData;
      setResult(res);
      setPreview(null);
      showToast(t("sync.completed"));
      await loadStatus();
      onSyncDone?.();
    } catch (err) {
      const msg = String(err).replace(/^Error:\s*/, "");
      setPreview(null);
      setError(msg);
      showToast(
        msg.toLowerCase().includes("preview") ? text.stale : msg,
        "error"
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="card">
      <h2>{t("sync.title")}</h2>
      <p className="field-hint" style={{ marginBottom: "var(--space-xl)" }}>
        {text.hint}
      </p>

      <p className="section-title">{t("sync.connectionStatus")}</p>
      {statusLoading ? (
        <LoadingSkeleton rows={3} />
      ) : (
        <dl className="status-grid">
          {(Object.entries(status) as [string, string][]).map(([key, value]) => {
            const disabled = value.includes("(disabled)");
            return (
              <div
                className={`status-row${
                  disabled ? " status-row-disabled" : ""
                }`}
                key={key}
              >
                <dt>{key.replace(/_/g, " ")}</dt>
                <dd>{value}</dd>
              </div>
            );
          })}
        </dl>
      )}

      <div className="button-row">
        <button
          className="primary"
          type="button"
          onClick={() => buildPreview(true, true)}
          disabled={anyBusy}
        >
          {busy === "preview" ? text.previewing : text.previewBoth}
        </button>
        <button
          className="secondary"
          type="button"
          onClick={() => buildPreview(false, true)}
          disabled={anyBusy}
        >
          {busy === "preview" ? text.previewing : text.previewPush}
        </button>
      </div>

      <p
        className="section-title"
        style={{ marginTop: "var(--space-xl)" }}
      >
        {t("sync.perSource")}
      </p>
      <div className="button-row" style={{ marginTop: 0 }}>
        {PULL_SOURCES.map((source) => {
          const statusVal = status[source] || "";
          const disabled =
            anyBusy || statusVal.includes("(disabled)");
          return (
            <button
              key={source}
              type="button"
              className="secondary"
              disabled={disabled}
              onClick={() => buildPreview(true, false, [source])}
              title={`${text.previewPull}: ${source}`}
            >
              {text.previewPull} {source}
            </button>
          );
        })}
      </div>

      {preview && (
        <section
          className="settings-section"
          aria-labelledby="sync-preview-heading"
          style={{ marginTop: "var(--space-xl)" }}
        >
          <h3 id="sync-preview-heading" className="section-title">
            {text.plan}
          </h3>
          <p className="field-hint">
            {text.expires}:{" "}
            {new Date(preview.expires_at).toLocaleString()}
          </p>

          <dl className="status-grid">
            {(Object.entries(preview.per_source) as [
              string,
              SyncSourcePreview
            ][]).map(([source, item]) => (
                <div className="status-row" key={source}>
                  <dt>
                    {source.replace(/_/g, " ")}
                    <br />
                    <span className="sync-muted">{item.status}</span>
                  </dt>
                  <dd>
                    {preview.include_pull && (
                      <div>
                        <strong>{text.pull}</strong>:{" "}
                        {text.remoteTotal} {item.pull.remote_total};{" "}
                        {text.add} {item.pull.add}; {text.update}{" "}
                        {item.pull.update}; {text.conflict}{" "}
                        {item.pull.conflict}; {text.unchanged}{" "}
                        {item.pull.unchanged}; {text.localOnly}{" "}
                        {item.pull.local_only}; {text.deleteObserved}{" "}
                        {item.pull.delete_observed}
                      </div>
                    )}
                    {preview.include_push && (
                      <div>
                        <strong>{text.push}</strong>: {text.create}{" "}
                        {item.push.create}; {text.update}{" "}
                        {item.push.update}; {text.delete}{" "}
                        {item.push.delete}; {text.pending}{" "}
                        {item.push.pending}
                      </div>
                    )}
                    {item.error && (
                      <div className="sync-error">{item.error}</div>
                    )}
                  </dd>
                </div>
              )
            )}
          </dl>

          <div className="result-panel">
            {text.add}: {preview.totals.pull_add}; {text.update}:{" "}
            {preview.totals.pull_update +
              preview.totals.push_update}
            ; {text.conflict}: {preview.totals.pull_conflict};{" "}
            {text.create}: {preview.totals.push_create};{" "}
            {text.delete}:{" "}
            {preview.totals.push_delete +
              preview.totals.pull_delete_observed}
            ; {text.pending}: {preview.totals.pending};{" "}
            {text.unavailable}:{" "}
            {preview.totals.unavailable_sources}
          </div>

          {preview.warnings.length > 0 && (
            <div className="error" role="alert">
              <strong>{text.warning}</strong>
              <ul>
                {preview.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="button-row">
            <button
              className="primary"
              type="button"
              disabled={anyBusy}
              onClick={executePreview}
            >
              {busy === "execute"
                ? text.executing
                : text.confirm}
            </button>
            <button
              className="secondary"
              type="button"
              disabled={anyBusy}
              onClick={() => setPreview(null)}
            >
              {t("confirm.cancel")}
            </button>
          </div>
        </section>
      )}

      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}

      {result && (
        <div style={{ marginTop: "var(--space-xl)" }}>
          <p className="section-title">{t("sync.lastOp")}</p>
          <SyncResultSummary result={result} />
          {conflictCount > 0 && onOpenConflicts && (
            <div className="button-row">
              <button
                type="button"
                className="primary"
                onClick={onOpenConflicts}
              >
                {t("sync.viewConflicts", {
                  count: conflictCount,
                })}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
