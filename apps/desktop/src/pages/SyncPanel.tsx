import { useEffect, useState } from "react";
import {
  api,
  type SyncPreview,
  type SyncPreviewOperation,
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
    operationDetails: "逐条变更",
    account: "账号",
    website: "网站",
    changedFields: "变化字段",
    noChangedFields: "无需改写内容字段",
    technicalDetails: "技术细节",
    nextStep: "下一步",
    reviewedDeletions: "我已查看这 {count} 个删除操作",
    willDeleteDevice: "将从这台设备删除",
    willDeleteService: "将从 {service} 删除",
    actions: {
      add: "新增",
      update: "更新",
      delete: "删除",
      conflict: "两处都发生了修改",
      unchanged: "不变",
      pending_verification: "结果待核对",
    },
    fields: {
      title: "名称",
      username: "用户名",
      password: "密码",
      url: "网站地址",
      notes: "备注",
    },
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
    operationDetails: "Item-level changes",
    account: "Account",
    website: "Website",
    changedFields: "Changed fields",
    noChangedFields: "No content fields need rewriting",
    technicalDetails: "Technical details",
    nextStep: "Next step",
    reviewedDeletions: "I reviewed these {count} deletion operations",
    willDeleteDevice: "Will be deleted from this device",
    willDeleteService: "Will be deleted from {service}",
    actions: {
      add: "Add",
      update: "Update",
      delete: "Delete",
      conflict: "Changed in both locations",
      unchanged: "Unchanged",
      pending_verification: "Pending verification",
    },
    fields: {
      title: "name",
      username: "username",
      password: "password",
      url: "website",
      notes: "notes",
    },
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
  const [deletionsReviewed, setDeletionsReviewed] = useState(false);

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
      setDeletionsReviewed(false);
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
    if (preview.destructive_count > 0 && !deletionsReviewed) return;

    setError("");
    setBusy("execute");
    try {
      const res = (await api.executeSync(
        preview.preview_token
      )) as SyncResultData;
      setResult(res);
      setPreview(null);
      setDeletionsReviewed(false);
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

  function actionLabel(action: SyncPreviewOperation["action"]): string {
    return text.actions[action];
  }

  function fieldLabel(field: string): string {
    return text.fields[field as keyof typeof text.fields] || field;
  }

  function interpolate(template: string, values: Record<string, string | number>): string {
    return Object.entries(values).reduce(
      (resultText, [key, value]) => resultText.replace(`{${key}}`, String(value)),
      template,
    );
  }

  function renderOperation(operation: SyncPreviewOperation) {
    const deletionText = operation.deletion_side === "this_device"
      ? text.willDeleteDevice
      : operation.deletion_side === "connected_service"
        ? interpolate(text.willDeleteService, { service: operation.source_label })
        : "";
    return (
      <li className="sync-operation" key={operation.operation_id}>
        <div className="sync-operation-heading">
          <strong>{operation.title || "—"}</strong>
          <span className="badge">{operation.direction === "pull" ? text.pull : text.push}</span>
        </div>
        <div className="sync-operation-meta">
          {operation.username_display && <span>{text.account}: {operation.username_display}</span>}
          {operation.website_host && <span>{text.website}: {operation.website_host}</span>}
        </div>
        {operation.changed_fields.length > 0 ? (
          <p>{text.changedFields}: {operation.changed_fields.map(fieldLabel).join(", ")}</p>
        ) : operation.action !== "delete" && (
          <p className="sync-muted">{text.noChangedFields}</p>
        )}
        {deletionText && <p className="sync-deletion-target">{deletionText}</p>}
        {operation.next_step && (
          <p className="sync-warning">{text.nextStep}: {operation.next_step.replace(/_/g, " ")}</p>
        )}
        <details>
          <summary>{text.technicalDetails}</summary>
          <dl className="sync-operation-technical">
            <div><dt>Operation ID</dt><dd>{operation.operation_id}</dd></div>
            {operation.local_id && <div><dt>Device ID</dt><dd>{operation.local_id}</dd></div>}
            {operation.remote_id && <div><dt>Service ID</dt><dd>{operation.remote_id}</dd></div>}
            <div><dt>Reason</dt><dd>{operation.reason}</dd></div>
          </dl>
        </details>
      </li>
    );
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

          <div className="sync-preview-sources">
            {(Object.entries(preview.per_source) as [
              string,
              SyncSourcePreview
            ][]).map(([source, item]) => {
              const grouped = item.operations.reduce<Record<string, SyncPreviewOperation[]>>(
                (groups, operation) => {
                  (groups[operation.action] ||= []).push(operation);
                  return groups;
                },
                {},
              );
              return (
                <section className="sync-source-preview" key={source}>
                  <h4>
                    {item.label || source.replace(/_/g, " ")}
                    <br />
                    <span className="sync-muted">{item.status}</span>
                  </h4>
                  <div className="sync-source-counts">
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
                  </div>
                  {item.operations.length > 0 && (
                    <div className="sync-operation-groups">
                      <strong>{text.operationDetails}</strong>
                      {Object.entries(grouped).map(([action, operations]) => (
                        <section
                          className={`sync-operation-group${action === "delete" ? " sync-operation-danger" : ""}`}
                          key={action}
                          aria-label={`${actionLabel(action as SyncPreviewOperation["action"])} ${operations.length}`}
                        >
                          <h5>{actionLabel(action as SyncPreviewOperation["action"])} ({operations.length})</h5>
                          <ul>{operations.map(renderOperation)}</ul>
                        </section>
                      ))}
                    </div>
                  )}
                </section>
              );
            })}
          </div>

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

          {preview.destructive_count > 0 && (
            <label className="checkbox-field sync-deletion-review">
              <input
                type="checkbox"
                checked={deletionsReviewed}
                onChange={(event) => setDeletionsReviewed(event.target.checked)}
              />
              <span>{interpolate(text.reviewedDeletions, { count: preview.destructive_count })}</span>
            </label>
          )}

          <div className="button-row">
            <button
              className="primary"
              type="button"
              disabled={anyBusy || (preview.destructive_count > 0 && !deletionsReviewed)}
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
              onClick={() => {
                setPreview(null);
                setDeletionsReviewed(false);
              }}
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
