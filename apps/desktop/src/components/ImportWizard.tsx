import { useEffect, useRef, useState } from "react";
import {
  api,
  type ImportApplyResult,
  type ImportPreview,
  type ImportPreviewItem,
} from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "./Toast";

type Resolution = {
  action: "skip" | "create" | "update";
  targetEntryId: string | null;
};

function humanBytes(bytes: number, zh: boolean): string {
  if (bytes < 1024) return `${bytes} ${zh ? "字节" : "bytes"}`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function classificationLabel(item: ImportPreviewItem, zh: boolean): string {
  if (item.classification === "new") return zh ? "将新增" : "Will add";
  if (item.classification === "exact_duplicate") return zh ? "完全重复，默认跳过" : "Identical, skipped by default";
  if (item.classification === "possible_duplicate") return zh ? "可能重复，需要选择" : "Possible duplicate; choose an action";
  return zh ? "无法导入，默认跳过" : "Cannot import; skipped by default";
}

export default function ImportWizard() {
  const { locale } = useI18n();
  const { showToast } = useToast();
  const zh = locale === "zh";
  const fileInput = useRef<HTMLInputElement | null>(null);
  const activePreviewToken = useRef<string | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [resolutions, setResolutions] = useState<Record<string, Resolution>>({});
  const [result, setResult] = useState<ImportApplyResult | null>(null);
  const [uncertainOutcome, setUncertainOutcome] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reviewed, setReviewed] = useState(false);

  useEffect(() => () => {
    const token = activePreviewToken.current;
    activePreviewToken.current = null;
    if (token) void api.cancelImport(token).catch(() => undefined);
  }, []);

  async function chooseFile(file: File) {
    setBusy(true);
    setResult(null);
    setUncertainOutcome(false);
    setReviewed(false);
    let plaintext = "";
    try {
      plaintext = await file.text();
      const format = file.name.toLowerCase().endsWith(".csv") ? "csv" : "json";
      const next = await api.previewImport(format, plaintext);
      const defaults: Record<string, Resolution> = {};
      for (const item of next.items) {
        defaults[item.preview_id] = {
          action: item.default_action,
          targetEntryId: null,
        };
      }
      activePreviewToken.current = next.preview_token;
      setPreview(next);
      setResolutions(defaults);
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
      setPreview(null);
      setResolutions({});
      setReviewed(false);
    } finally {
      plaintext = "";
      if (fileInput.current) fileInput.current.value = "";
      setBusy(false);
    }
  }

  function updateResolution(item: ImportPreviewItem, encoded: string) {
    if (encoded.startsWith("update:")) {
      setResolutions((current) => ({
        ...current,
        [item.preview_id]: {
          action: "update",
          targetEntryId: encoded.slice("update:".length),
        },
      }));
      return;
    }
    setResolutions((current) => ({
      ...current,
      [item.preview_id]: {
        action: encoded as "skip" | "create",
        targetEntryId: null,
      },
    }));
  }

  async function cancelPreview() {
    const token = preview?.preview_token;
    activePreviewToken.current = null;
    setBusy(true);
    try {
      if (token) await api.cancelImport(token);
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    } finally {
      setPreview(null);
      setResolutions({});
      setReviewed(false);
      setBusy(false);
    }
  }

  async function applyPreview() {
    if (!preview || !reviewed) return;
    setBusy(true);
    activePreviewToken.current = null;
    try {
      const decisions = preview.items.map((item) => ({
        preview_id: item.preview_id,
        action: resolutions[item.preview_id]?.action || item.default_action,
        target_entry_id: resolutions[item.preview_id]?.targetEntryId || null,
      }));
      const applied = await api.applyImport(preview.preview_token, decisions);
      setResult(applied);
      setPreview(null);
      setResolutions({});
      showToast(
        zh
          ? `导入完成：新增 ${applied.added}，更新 ${applied.updated}，跳过 ${applied.skipped}`
          : `Import complete: ${applied.added} added, ${applied.updated} updated, ${applied.skipped} skipped`,
      );
    } catch (error) {
      if (error instanceof TypeError) {
        setUncertainOutcome(true);
        showToast(
          zh
            ? "无法确认导入结果。请先到密码页检查，确认前不要重复导入。"
            : "The import outcome could not be confirmed. Check Passwords before importing the file again.",
          "error",
        );
      } else {
        showToast(String(error).replace(/^Error:\s*/, ""), "error");
      }
      setPreview(null);
      setResolutions({});
      setReviewed(false);
    } finally {
      setBusy(false);
    }
  }

  async function undo() {
    const transactionId = result?.receipt?.transaction_id;
    if (!transactionId) return;
    setBusy(true);
    try {
      await api.undoImport(transactionId);
      setResult((current) => current ? {
        ...current,
        receipt: current.receipt ? { ...current.receipt, undone: true } : null,
      } : current);
      showToast(zh ? "本次导入已撤销" : "This import was undone");
    } catch (error) {
      showToast(String(error).replace(/^Error:\s*/, ""), "error");
    } finally {
      setBusy(false);
    }
  }

  const possibleDuplicates = preview?.items.filter(
    (item) => item.classification === "possible_duplicate",
  ) || [];
  const selectedAdd = preview?.items.filter(
    (item) => (resolutions[item.preview_id]?.action || item.default_action) === "create",
  ).length || 0;
  const selectedUpdate = preview?.items.filter(
    (item) => resolutions[item.preview_id]?.action === "update",
  ).length || 0;
  const selectedSkipped = (preview?.counts.total || 0) - selectedAdd - selectedUpdate;

  return (
    <div className="import-wizard" aria-labelledby="import-wizard-heading">
      <h4 id="import-wizard-heading">{zh ? "导入密码" : "Import passwords"}</h4>
      <ol className="import-steps" aria-label={zh ? "导入步骤" : "Import steps"}>
        <li className={!preview && !result ? "is-current" : ""}>{zh ? "选择文件" : "Choose file"}</li>
        <li>{zh ? "解析与验证" : "Parse and validate"}</li>
        <li className={preview ? "is-current" : ""}>{zh ? "预览" : "Preview"}</li>
        <li className={possibleDuplicates.length ? "is-current" : ""}>{zh ? "处理重复项" : "Resolve duplicates"}</li>
        <li>{zh ? "确认应用" : "Confirm"}</li>
        <li className={result ? "is-current" : ""}>{zh ? "结果与撤销" : "Result and undo"}</li>
      </ol>

      {!preview && !result && !uncertainOutcome && (
        <div className="button-row">
          <label className={`secondary file-button${busy ? " is-disabled" : ""}`}>
            {busy ? (zh ? "正在安全解析…" : "Parsing safely…") : (zh ? "选择 JSON / CSV 文件" : "Choose JSON / CSV file")}
            <input
              ref={fileInput}
              type="file"
              accept=".json,.csv,application/json,text/csv"
              disabled={busy}
              onChange={(event) => event.target.files?.[0] && chooseFile(event.target.files[0])}
              hidden
            />
          </label>
        </div>
      )}

      {uncertainOutcome && !preview && !result && (
        <div className="error" role="status">
          <p>
            {zh
              ? "导入结果未知：网络可能在提交后中断。请打开“密码”检查实际结果；确认前不要再次导入同一文件。"
              : "Import outcome unknown: the connection may have stopped after commit. Open Passwords and inspect the actual result before importing the same file again."}
          </p>
          <button className="secondary" type="button" onClick={() => setUncertainOutcome(false)}>
            {zh ? "我已检查实际结果" : "I checked the actual result"}
          </button>
        </div>
      )}

      {preview && (
        <div className="import-preview" aria-live="polite">
          <div className="import-summary">
            <dl><dt>{zh ? "文件条目" : "File entries"}</dt><dd>{preview.counts.total}</dd></dl>
            <dl><dt>{zh ? "可导入" : "Importable"}</dt><dd>{preview.counts.importable}</dd></dl>
            <dl><dt>{zh ? "将新增" : "Will add"}</dt><dd>{selectedAdd}</dd></dl>
            <dl><dt>{zh ? "将更新" : "Will update"}</dt><dd>{selectedUpdate}</dd></dl>
            <dl><dt>{zh ? "将跳过" : "Will skip"}</dt><dd>{selectedSkipped}</dd></dl>
            <dl><dt>{zh ? "完全重复" : "Identical"}</dt><dd>{preview.counts.exact_duplicates}</dd></dl>
            <dl><dt>{zh ? "可能重复" : "Possible duplicates"}</dt><dd>{preview.counts.possible_duplicates}</dd></dl>
            <dl><dt>{zh ? "格式问题" : "Format issues"}</dt><dd>{preview.counts.format_errors}</dd></dl>
            <dl><dt>{zh ? "不支持字段" : "Unsupported fields"}</dt><dd>{preview.counts.unsupported_fields}</dd></dl>
            <dl><dt>{zh ? "附件" : "Attachments"}</dt><dd>{preview.counts.attachments} · {humanBytes(preview.counts.attachment_bytes, zh)}</dd></dl>
          </div>

          <ul className="import-item-list">
            {preview.items.map((item) => (
              <li key={item.preview_id} className={`import-item import-item-${item.classification}`}>
                <div className="import-item-heading">
                  <strong>{item.title || (zh ? `第 ${item.index} 条` : `Item ${item.index}`)}</strong>
                  <span>{classificationLabel(item, zh)}</span>
                </div>
                {(item.username || item.host) && (
                  <div className="field-hint">{[item.username, item.host].filter(Boolean).join(" · ")}</div>
                )}
                {item.unsupported_fields.length > 0 && (
                  <div className="field-hint">
                    {zh ? "不支持的字段：" : "Unsupported fields: "}{item.unsupported_fields.join(", ")}
                  </div>
                )}
                {item.reason && item.classification === "invalid" && (
                  <div className="field-hint">
                    {zh ? "跳过原因：" : "Skip reason: "}{item.reason}
                  </div>
                )}
                {item.classification === "possible_duplicate" && (
                  <div className="field">
                    <label className="field-label" htmlFor={`import-resolution-${item.preview_id}`}>
                      {zh ? "如何处理" : "What to do"}
                    </label>
                    <select
                      id={`import-resolution-${item.preview_id}`}
                      value={
                        resolutions[item.preview_id]?.action === "update"
                          ? `update:${resolutions[item.preview_id].targetEntryId}`
                          : resolutions[item.preview_id]?.action || "skip"
                      }
                      onChange={(event) => updateResolution(item, event.target.value)}
                    >
                      <option value="skip">{zh ? "跳过（推荐）" : "Skip (recommended)"}</option>
                      <option value="create">{zh ? "作为新条目导入" : "Import as a new entry"}</option>
                      {item.candidates.map((candidate) => (
                        <option key={candidate.id} value={`update:${candidate.id}`}>
                          {zh ? `更新现有条目：${candidate.title}` : `Update existing: ${candidate.title}`}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </li>
            ))}
          </ul>

          <details className="technical-details">
            <summary>{zh ? "技术细节" : "Technical details"}</summary>
            <div>{zh ? "文件 SHA-256：" : "File SHA-256: "}<code>{preview.source_file_digest}</code></div>
            <div>{zh ? "预览有效期至：" : "Preview expires: "}{preview.expires_at}</div>
          </details>

          <label className="checkbox-field">
            <input type="checkbox" checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} />
            <span>{zh ? "我已查看新增、重复项和跳过原因" : "I reviewed additions, duplicates, and skip reasons"}</span>
          </label>
          <div className="button-row">
            <button className="primary" type="button" disabled={!reviewed || busy} onClick={applyPreview}>
              {busy ? (zh ? "正在原子应用…" : "Applying atomically…") : (zh ? "确认导入" : "Confirm import")}
            </button>
            <button className="secondary" type="button" disabled={busy} onClick={cancelPreview}>
              {zh ? "取消导入" : "Cancel import"}
            </button>
          </div>
        </div>
      )}

      {result && (
        <div className="import-result" aria-live="polite">
          <h5>{zh ? "导入结果" : "Import result"}</h5>
          <p>
            {zh
              ? `新增 ${result.added} 条，更新 ${result.updated} 条，跳过 ${result.skipped} 条。`
              : `${result.added} added, ${result.updated} updated, ${result.skipped} skipped.`}
          </p>
          <p className="field-hint">
            {zh
              ? "导入结果只保存在这台设备；不会自动发送到已连接的服务。"
              : "Imported changes stay on this device and are not sent to connected services automatically."}
          </p>
          {result.receipt && !result.receipt.undone && (
            <button className="secondary" type="button" disabled={busy} onClick={undo}>
              {busy ? (zh ? "正在安全撤销…" : "Undoing safely…") : (zh ? "撤销本次导入" : "Undo this import")}
            </button>
          )}
          {result.receipt?.undone && <p>{zh ? "本次导入已撤销。" : "This import has been undone."}</p>}
          <button className="secondary" type="button" disabled={busy} onClick={() => setResult(null)}>
            {zh ? "完成" : "Done"}
          </button>
        </div>
      )}
    </div>
  );
}
