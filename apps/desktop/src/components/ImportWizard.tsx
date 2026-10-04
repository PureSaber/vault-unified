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

type ImportSource = "auto" | "chrome" | "edge";

function importMessage(message: string, zh: boolean): string {
  if (!zh) return message;
  const translations: Record<string, string> = {
    "Browser CSV needs url, username and password columns": "文件缺少网站、用户名或密码列，请重新从浏览器导出 CSV。",
    "Browser CSV contains unrecognized columns; export it again from Chrome or Edge": "文件含有无法识别的列，请重新从 Chrome 或 Edge 导出，保留原始格式。",
    "Browser CSV has ambiguous note columns": "文件包含两列备注，无法确定应该使用哪一列。",
    "Browser CSV has no password rows": "文件中没有可读取的密码记录。",
    "Browser row has missing or extra cells": "这条记录的列数与表头不一致。",
    "Browser row needs a valid website or Android app address": "这条记录缺少有效的网站或 Android 应用地址。",
    "Browser row has no password": "这条记录没有密码。",
    "Transfer CSV is missing a header": "CSV 文件缺少表头。",
    "Transfer CSV has duplicate column names": "CSV 文件包含重复的列名。",
    "Transfer CSV is invalid": "CSV 格式无法解析，请重新导出后再试。",
    "Transfer file exceeds the 10 MiB limit": "文件超过 10 MiB，请分批导入。",
    "Transfer contains too many entries": "文件超过 5,000 条记录，请分批导入。",
  };
  return translations[message] || message;
}

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

export default function ImportWizard({ initialSource = "auto", onDone }: { initialSource?: ImportSource; onDone?: () => void }) {
  const { locale } = useI18n();
  const { showToast } = useToast();
  const zh = locale === "zh";
  const fileInput = useRef<HTMLInputElement | null>(null);
  const activePreviewToken = useRef<string | null>(null);
  const operation = useRef(0);
  const [source, setSource] = useState<ImportSource>(initialSource);
  const [problem, setProblem] = useState("");
  const [browserImport, setBrowserImport] = useState(false);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [resolutions, setResolutions] = useState<Record<string, Resolution>>({});
  const [result, setResult] = useState<ImportApplyResult | null>(null);
  const [uncertainOutcome, setUncertainOutcome] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reviewed, setReviewed] = useState(false);

  useEffect(() => () => {
    operation.current += 1;
    const token = activePreviewToken.current;
    activePreviewToken.current = null;
    if (token) void api.cancelImport(token).catch(() => undefined);
  }, []);

  async function chooseFile(file: File) {
    const current = ++operation.current;
    setBusy(true);
    setProblem("");
    setResult(null);
    setUncertainOutcome(false);
    setReviewed(false);
    let plaintext = "";
    try {
      if (file.size > 10 * 1024 * 1024) throw new Error("Transfer file exceeds the 10 MiB limit");
      const csv = file.name.toLowerCase().endsWith(".csv");
      if (source !== "auto" && !csv) throw new Error(zh ? "请选择浏览器导出的 CSV 文件。" : "Choose the CSV file exported by your browser.");
      try {
        plaintext = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
      } catch {
        throw new Error(zh ? "文件不是有效的 UTF-8 文本，请直接使用浏览器导出的原始文件。" : "This file is not valid UTF-8. Use the original browser export.");
      }
      if (current !== operation.current) return;
      const format = source !== "auto" ? "browser_csv" : csv ? "csv" : "json";
      const next = await api.previewImport(format, plaintext);
      if (current !== operation.current) {
        void api.cancelImport(next.preview_token).catch(() => undefined);
        return;
      }
      const defaults: Record<string, Resolution> = {};
      for (const item of next.items) {
        defaults[item.preview_id] = {
          action: item.default_action,
          targetEntryId: null,
        };
      }
      activePreviewToken.current = next.preview_token;
      setBrowserImport(next.source_format === "chromium_csv");
      setPreview(next);
      setResolutions(defaults);
    } catch (error) {
      if (current !== operation.current) return;
      const message = importMessage(String(error).replace(/^Error:\s*/, ""), zh);
      setProblem(message);
      setPreview(null);
      setResolutions({});
      setReviewed(false);
    } finally {
      plaintext = "";
      if (current === operation.current) {
        if (fileInput.current) fileInput.current.value = "";
        setBusy(false);
      }
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
        <div>
          <div className="field">
            <label className="field-label" htmlFor="import-source">{zh ? "密码来源" : "Import source"}</label>
            <select id="import-source" value={source} disabled={busy} onChange={(event) => { setSource(event.target.value as ImportSource); setProblem(""); }}>
              <option value="auto">{zh ? "自动识别 JSON / CSV" : "Detect JSON / CSV automatically"}</option>
              <option value="chrome">Google Chrome</option>
              <option value="edge">Microsoft Edge</option>
            </select>
          </div>
          {source !== "auto" && (
            <div className="import-browser-guide">
              <p><strong>{zh ? "先从浏览器导出密码" : "Export passwords from your browser first"}</strong></p>
              <ol>
                <li>{source === "chrome"
                  ? (zh ? "打开 Chrome 菜单 → 密码和自动填充 → Google 密码管理工具 → 设置。" : "Open the Chrome menu → Passwords and autofill → Google Password Manager → Settings.")
                  : (zh ? "打开 Edge 菜单（Alt+F）→ 密码。" : "Open the Edge menu (Alt+F) → Passwords.")}</li>
                <li>{source === "chrome"
                  ? (zh ? "找到“导出密码”，下载 CSV 文件，并按浏览器提示验证身份。" : "Find Export passwords, download the CSV file, and complete the browser's identity check.")
                  : (zh ? "在密码页面打开更多选项 → 导出密码，确认并保存 CSV 文件。" : "On the passwords page, open the options menu → Export passwords, then confirm and save the CSV file.")}</li>
                <li>{zh ? "在下方选择原始文件，无需用 Excel 打开或修改。" : "Choose the original file below. There is no need to edit it in Excel."}</li>
              </ol>
              <p className="field-hint">{zh ? "文件含有明文密码。导入并检查结果后，请删除导出的 CSV。导入不会删除浏览器里的密码。" : "The file contains plaintext passwords. Delete the exported CSV after checking the import. Importing does not delete passwords from your browser."}</p>
            </div>
          )}
          <p className="field-hint">{zh ? "先预览再保存；支持 Chrome / Edge CSV 和 Vault Unified 导出文件，每次最多 5,000 条、10 MiB。" : "Preview before saving. Supports Chrome / Edge CSV and Vault Unified exports, up to 5,000 records and 10 MiB per file."}</p>
          {problem && <div className="error" role="alert">{problem}</div>}
          <div className="button-row">
          <button type="button" className="secondary" disabled={busy} onClick={() => fileInput.current?.click()}>
            {busy ? (zh ? "正在解析…" : "Parsing…") : source === "auto" ? (zh ? "选择 JSON / CSV 文件" : "Choose JSON / CSV file") : (zh ? "选择浏览器 CSV 文件" : "Choose browser CSV file")}
          </button>
            <input
              ref={fileInput}
              type="file"
              aria-label={source === "auto" ? (zh ? "选择 JSON / CSV 文件" : "Choose JSON / CSV file") : (zh ? "选择浏览器 CSV 文件" : "Choose browser CSV file")}
              accept={source === "auto" ? ".json,.csv,application/json,text/csv" : ".csv,text/csv"}
              disabled={busy}
              onChange={(event) => event.target.files?.[0] && chooseFile(event.target.files[0])}
              hidden
            />
          </div>
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
          {browserImport && <>
            <p>{zh ? "已识别 Chrome / Edge 密码文件。密码和备注不会显示在预览中。" : "Recognized a Chrome / Edge password file. Passwords and notes stay hidden in this preview."}</p>
            <p className="field-hint">{zh ? "选择更新时，只替换文件提供的登录字段和备注；保留已有标签、验证器密钥、自定义字段、附件和历史。" : "Updating replaces only login fields and notes supplied by the file. Existing tags, authenticator keys, custom fields, attachments and history are kept."}</p>
          </>}
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
                {item.title && <div className="field-hint">{zh ? `文件中的第 ${item.index} 条记录` : `Record ${item.index} in the file`}</div>}
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
                    {zh ? "跳过原因：" : "Skip reason: "}{importMessage(item.reason, zh)}
                  </div>
                )}
                {browserImport && item.classification === "new" && (
                  <label className="checkbox-field">
                    <input type="checkbox" disabled={busy} checked={resolutions[item.preview_id]?.action !== "skip"}
                      onChange={(event) => updateResolution(item, event.target.checked ? "create" : "skip")} />
                    <span>{zh ? `导入 ${item.title}` : `Import ${item.title}`}</span>
                  </label>
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
              {busy ? (zh ? "正在导入…" : "Importing…") : (zh ? "确认导入" : "Confirm import")}
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
          {browserImport && <p className="field-hint">{zh ? "请检查导入的账号，确认后删除浏览器导出的明文 CSV 文件。浏览器里的原始密码仍然保留。" : "Check the imported accounts, then delete the plaintext CSV exported by your browser. Your original browser passwords are still there."}</p>}
          {result.receipt && !result.receipt.undone && (
            <button className="secondary" type="button" disabled={busy} onClick={undo}>
              {busy ? (zh ? "正在安全撤销…" : "Undoing safely…") : (zh ? "撤销本次导入" : "Undo this import")}
            </button>
          )}
          {result.receipt?.undone && <p>{zh ? "本次导入已撤销。" : "This import has been undone."}</p>}
          <button className="secondary" type="button" disabled={busy} onClick={() => { setResult(null); onDone?.(); }}>
            {zh ? "完成" : "Done"}
          </button>
        </div>
      )}
    </div>
  );
}
