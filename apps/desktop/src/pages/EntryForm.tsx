import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Attachment, type Entry, type TemplateData, type WebsiteRules } from "../api/client";
import CredentialTemplateFields from "../components/CredentialTemplateFields";
import TotpEditor from "../components/TotpEditor";
import GeneratorOptions, { defaultGenerationOptions } from "../components/GeneratorOptions";
import GenerationHistory from "../components/GenerationHistory";
import WebsiteRulesEditor, { normalizedWebsiteRules } from "../components/WebsiteRulesEditor";
import HistoryReview, { type HistoryField } from "../components/HistoryReview";
import PasswordField from "../components/PasswordField";
import { useToast } from "../components/Toast";
import { useI18n } from "../i18n";

interface Props {
  entry?: Entry | null;
  onDone: (saved?: boolean) => void;
  onDirtyChange?: (dirty: boolean) => void;
  onSavingChange?: (saving: boolean) => void;
}

type EntryType = Entry["entry_type"];
type CustomField = { clientId: string; label: string; value: string; concealed: boolean };
type PendingAttachment = { clientId: string; file: File };
type Draft = {
  title: string;
  username: string;
  password: string;
  url: string;
  notes: string;
  tags: string[];
  entryType: EntryType;
  customFields: CustomField[];
  totpSecret: string;
  templateData: TemplateData;
  websiteRules: WebsiteRules;
  attachments: Attachment[];
  pendingAttachments: PendingAttachment[];
  restoreHistoryId: string | null;
};

const SUPPORTED_NEW_TYPES: EntryType[] = ["login", "secure_note", "recovery_code", "software_license", "api_credential"];

const copy = {
  zh: {
    addLogin: "添加密码",
    addNote: "添加安全备注",
    editLogin: "编辑密码",
    editNote: "编辑安全备注",
    editCompatibility: "编辑兼容条目",
    type: "内容类型",
    websiteName: "网站或应用名称",
    noteTitle: "备注名称",
    login: "登录信息",
    secureNote: "安全备注",
    card: "卡片（兼容）",
    identity: "身份信息（兼容）",
    sshKey: "SSH 密钥（兼容）",
    recoveryCode: "恢复码",
    compatibilityHint: "这是由旧版本或导入保留的兼容条目。原类型和现有字段会原样保留；在专用表单完成前，不能新建此类型。",
    website: "网站地址",
    more: "更多选项",
    less: "收起更多选项",
    noAdvanced: "标签、验证器密钥、自定义字段、附件和历史",
    tags: "标签",
    tagInput: "添加标签",
    tagPlaceholder: "输入标签后按 Enter",
    addTag: "添加",
    removeTag: "移除标签 {tag}",
    authenticatorKey: "验证器密钥（TOTP 密钥）",
    customFields: "自定义字段",
    fieldLabel: "字段名称",
    fieldValue: "字段内容",
    conceal: "隐藏内容",
    remove: "移除",
    addField: "添加自定义字段",
    customFieldError: "每个自定义字段都必须填写字段名称。",
    attachments: "附件",
    attachmentHint: "使用系统文件选择器。附件更改只在保存整个条目时一起提交；取消不会写入。",
    chooseAttachments: "选择附件",
    download: "下载",
    removeOnSave: "保存时删除",
    removePending: "移除待添加文件",
    history: "历史版本",
    noHistory: "尚无历史版本。",
    previewHistory: "载入草稿预览",
    generatorOptions: "密码生成高级选项",
    hideGeneratorOptions: "收起密码生成选项",
    technical: "技术来源与同步信息",
    hideTechnical: "隐藏技术来源与同步信息",
    source: "来源标识",
    syncState: "同步状态",
    linkedServices: "关联服务",
    none: "无",
    existingSummary: "已有更多内容：{summary}",
    tagsSummary: "{count} 个标签",
    totpSummary: "验证器密钥",
    customSummary: "{count} 个自定义字段",
    attachmentSummary: "{count} 个附件",
    historySummary: "{count} 个历史版本",
    restoredSummary: "已载入历史草稿",
    loadedDraft: "历史版本已载入草稿；保存前不会修改保险库",
  },
  en: {
    addLogin: "Add password",
    addNote: "Add secure note",
    editLogin: "Edit password",
    editNote: "Edit secure note",
    editCompatibility: "Edit compatibility entry",
    type: "Content type",
    websiteName: "Website or app name",
    noteTitle: "Note title",
    login: "Login",
    secureNote: "Secure note",
    card: "Card (compatibility)",
    identity: "Identity (compatibility)",
    sshKey: "SSH key (compatibility)",
    recoveryCode: "Recovery codes",
    compatibilityHint: "This compatibility entry was retained from an earlier version or import. Its original type and fields remain intact; this type cannot be newly created until a dedicated form exists.",
    website: "Website address",
    more: "More options",
    less: "Collapse more options",
    noAdvanced: "Tags, authenticator key, custom fields, attachments, and history",
    tags: "Tags",
    tagInput: "Add a tag",
    tagPlaceholder: "Type a tag and press Enter",
    addTag: "Add",
    removeTag: "Remove tag {tag}",
    authenticatorKey: "Authenticator key (TOTP key)",
    customFields: "Custom fields",
    fieldLabel: "Field name",
    fieldValue: "Field content",
    conceal: "Conceal content",
    remove: "Remove",
    addField: "Add custom field",
    customFieldError: "Every custom field needs a field name.",
    attachments: "Attachments",
    attachmentHint: "Uses the system file picker. Attachment changes commit with the whole entry; Cancel writes nothing.",
    chooseAttachments: "Choose attachments",
    download: "Download",
    removeOnSave: "Remove on save",
    removePending: "Remove pending file",
    history: "Version history",
    noHistory: "No saved versions yet.",
    previewHistory: "Preview in draft",
    generatorOptions: "Password generator advanced options",
    hideGeneratorOptions: "Collapse generator options",
    technical: "Technical source and sync information",
    hideTechnical: "Hide technical source and sync information",
    source: "Source identifier",
    syncState: "Sync state",
    linkedServices: "Linked services",
    none: "None",
    existingSummary: "More content already saved: {summary}",
    tagsSummary: "{count} tag(s)",
    totpSummary: "authenticator key",
    customSummary: "{count} custom field(s)",
    attachmentSummary: "{count} attachment(s)",
    historySummary: "{count} saved version(s)",
    restoredSummary: "history draft loaded",
    loadedDraft: "Version loaded into the draft; the vault is unchanged until you save",
  },
} as const;

function clientId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `draft-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function emptyDraft(): Draft {
  return {
    title: "",
    username: "",
    password: "",
    url: "",
    notes: "",
    tags: [],
    entryType: "login",
    customFields: [],
    totpSecret: "",
    templateData: {},
    websiteRules: normalizedWebsiteRules(),
    attachments: [],
    pendingAttachments: [],
    restoreHistoryId: null,
  };
}

function draftFromEntry(entry: Entry): Draft {
  return {
    title: entry.title || "",
    username: entry.username || "",
    password: entry.password || "",
    url: entry.url || "",
    notes: entry.notes || "",
    tags: [...(entry.tags || [])],
    entryType: entry.entry_type || "login",
    customFields: (entry.custom_fields || []).map((field) => ({ ...field, clientId: clientId() })),
    totpSecret: entry.totp_secret || "",
    templateData: structuredClone(entry.template_data || {}),
    websiteRules: structuredClone(normalizedWebsiteRules(entry.website_rules)),
    attachments: [...(entry.attachments || [])],
    pendingAttachments: [],
    restoreHistoryId: null,
  };
}

function fingerprint(draft: Draft): string {
  return JSON.stringify({
    title: draft.title,
    username: draft.username,
    password: draft.password,
    url: draft.url,
    notes: draft.notes,
    tags: draft.tags,
    entryType: draft.entryType,
    customFields: draft.customFields.map(({ label, value, concealed }) => ({ label, value, concealed })),
    totpSecret: draft.totpSecret,
    templateData: draft.templateData,
    websiteRules: draft.websiteRules,
    attachmentIds: draft.attachments.map((item) => item.id),
    pendingAttachments: draft.pendingAttachments.map(({ clientId: id, file }) => ({
      id,
      name: file.name,
      size: file.size,
      type: file.type,
      lastModified: file.lastModified,
    })),
    restoreHistoryId: draft.restoreHistoryId,
  });
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Could not read attachment"));
    reader.onload = () => {
      const value = String(reader.result || "");
      resolve(value.slice(value.indexOf(",") + 1));
    };
    reader.readAsDataURL(file);
  });
}

function downloadAttachment(filename: string, mimeType: string, dataB64: string) {
  const raw = atob(dataB64);
  const bytes = Uint8Array.from(raw, (character) => character.charCodeAt(0));
  const blob = new Blob([bytes], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function interpolate(template: string, values: Record<string, string | number>) {
  return Object.entries(values).reduce(
    (value, [key, replacement]) => value.split(`{${key}}`).join(String(replacement)),
    template,
  );
}

export default function EntryForm({ entry, onDone, onDirtyChange, onSavingChange }: Props) {
  const { t, locale } = useI18n();
  const text = copy[locale];
  const { showToast } = useToast();
  const isEdit = Boolean(entry);
  const initial = useMemo(emptyDraft, []);
  const [original, setOriginal] = useState<Draft>(initial);
  const [draft, setDraft] = useState<Draft>(initial);
  const [loading, setLoading] = useState(isEdit);
  const [personalReady, setPersonalReady] = useState(false);
  const [history, setHistory] = useState<Array<{ id: string; saved_at: string }>>([]);
  const [historyToRestore, setHistoryToRestore] = useState<string | null>(null);
  const [generationOptions, setGenerationOptions] = useState(defaultGenerationOptions);
  const [generating, setGenerating] = useState(false);
  const [showGenerationHistory, setShowGenerationHistory] = useState(false);
  const generationSequence = useRef(0);
  const latestPassword = useRef(draft.password);
  latestPassword.current = draft.password;
  useEffect(() => () => { ++generationSequence.current; }, []);
  const [showGeneratorOptions, setShowGeneratorOptions] = useState(false);
  const [showMore, setShowMore] = useState(false);
  const [showTechnical, setShowTechnical] = useState(false);
  const [tagInput, setTagInput] = useState("");
  const [advancedError, setAdvancedError] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const transactionId = useRef(clientId());

  const dirty = fingerprint(draft) !== fingerprint(original);
  const isSecureNote = draft.entryType === "secure_note";
  const isTemplate = ["recovery_code", "software_license", "api_credential"].includes(draft.entryType);
  const isCompatibility = !SUPPORTED_NEW_TYPES.includes(draft.entryType);

  useEffect(() => { void api.payloadFormat().then(format => setPersonalReady(format.version >= 3)).catch(() => {}); }, []);

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  useEffect(() => {
    onSavingChange?.(saving);
  }, [saving, onSavingChange]);

  useEffect(() => () => {
    onDirtyChange?.(false);
    onSavingChange?.(false);
  }, [onDirtyChange, onSavingChange]);

  useEffect(() => {
    transactionId.current = clientId();
    setShowMore(false);
    setShowTechnical(false);
    setShowGeneratorOptions(false);
    setTagInput("");
    setAdvancedError("");
    if (!entry) {
      const blank = emptyDraft();
      setOriginal(blank);
      setDraft(blank);
      setHistory([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    Promise.all([api.getEntry(entry.id, true), api.entryHistory(entry.id, false)])
      .then(([full, historyResult]) => {
        if (cancelled) return;
        const loaded = draftFromEntry(full);
        setOriginal(loaded);
        setDraft(loaded);
        setHistory(historyResult.history.map((item) => ({ id: item.id, saved_at: item.saved_at })));
      })
      .catch((loadError) => {
        if (cancelled) return;
        const message = String(loadError).replace(/^Error:\s*/, "");
        setError(message);
        showToast(message, "error");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [entry, showToast]);

  const advancedSummary = useMemo(() => {
    const summary: string[] = [];
    if (draft.tags.length) summary.push(interpolate(text.tagsSummary, { count: draft.tags.length }));
    if (draft.totpSecret) summary.push(text.totpSummary);
    if (draft.websiteRules.match !== "exact" || draft.websiteRules.additional_urls.length || draft.websiteRules.excluded_urls.length) summary.push(locale === "zh" ? "网站匹配规则" : "Website matching rules");
    if (draft.customFields.length) summary.push(interpolate(text.customSummary, { count: draft.customFields.length }));
    const attachmentCount = draft.attachments.length + draft.pendingAttachments.length;
    if (attachmentCount) summary.push(interpolate(text.attachmentSummary, { count: attachmentCount }));
    if (history.length) summary.push(interpolate(text.historySummary, { count: history.length }));
    if (draft.restoreHistoryId) summary.push(text.restoredSummary);
    return summary;
  }, [draft.attachments.length, draft.customFields.length, draft.pendingAttachments.length, draft.restoreHistoryId, draft.tags.length, draft.totpSecret, draft.websiteRules, history.length, text, locale]);

  function patchDraft(patch: Partial<Draft>) {
    setDraft((current) => ({ ...current, ...patch }));
  }

  function entryTypeLabel(type: EntryType): string {
    const labels: Record<EntryType, string> = {
      login: text.login,
      secure_note: text.secureNote,
      card: text.card,
      identity: text.identity,
      ssh_key: text.sshKey,
      recovery_code: text.recoveryCode,
      software_license: locale === "zh" ? "软件许可证" : "Software license",
      api_credential: locale === "zh" ? "API 凭据" : "API credential",
    };
    return labels[type];
  }

  function heading(): string {
    if (isTemplate) return `${locale === "zh" ? (isEdit ? "编辑" : "添加") : (isEdit ? "Edit " : "Add ")}${entryTypeLabel(draft.entryType)}`;
    if (!isEdit) return isSecureNote ? text.addNote : text.addLogin;
    if (isCompatibility) return text.editCompatibility;
    return isSecureNote ? text.editNote : text.editLogin;
  }

  async function handleGenerate() {
    if (generating) return;
    const stamp = ++generationSequence.current;
    const previous = draft.password;
    setGenerating(true);
    try {
      const result = personalReady
        ? await api.generateSaved(generationOptions, draft.url, clientId())
        : await api.generate(generationOptions.length, generationOptions.symbols);
      if (stamp !== generationSequence.current) return;
      if (latestPassword.current === previous) patchDraft({ password: result.password });
      showToast(personalReady ? (locale === "zh" ? "已生成并加入加密历史" : "Generated and kept in encrypted history") : t("form.generated"));
    } catch (generateError) {
      if (stamp === generationSequence.current) showToast(locale === "zh" ? "生成失败，请检查字符限制或重试。" : "Could not generate. Check character restrictions or try again.", "error");
    } finally {
      if (stamp === generationSequence.current) setGenerating(false);
    }
  }

  function addTag() {
    const nextTag = tagInput.trim().normalize("NFC");
    if (!nextTag) return;
    if (!draft.tags.some((tag) => tag.toLocaleLowerCase() === nextTag.toLocaleLowerCase())) {
      patchDraft({ tags: [...draft.tags, nextTag] });
    }
    setTagInput("");
  }

  async function handleSave(event: React.FormEvent) {
    event.preventDefault();
    if (saving) return;
    const invalidCustomField = draft.customFields.some((field) => !field.label.trim());
    if (invalidCustomField) {
      setAdvancedError(text.customFieldError);
      setShowMore(true);
      window.requestAnimationFrame(() => document.getElementById("entry-advanced-error")?.focus());
      return;
    }
    setAdvancedError("");
    setError("");
    setSaving(true);
    try {
      const addAttachments = await Promise.all(
        draft.pendingAttachments.map(async ({ file }) => ({
          filename: file.name,
          mime_type: file.type || "application/octet-stream",
          data_b64: await fileToBase64(file),
        })),
      );
      const keptIds = new Set(draft.attachments.map((attachment) => attachment.id));
      await api.commitEntry({
        transaction_id: transactionId.current,
        entry_id: entry?.id ?? null,
        expected_updated_at: entry?.updated_at ?? null,
        title: draft.title,
        username: draft.username,
        password: draft.password,
        url: draft.url,
        notes: draft.notes,
        tags: draft.tags,
        entry_type: draft.entryType,
        template_data: draft.templateData,
        website_rules: draft.websiteRules,
        custom_fields: draft.customFields.map(({ label, value, concealed }) => ({ label, value, concealed })),
        totp_secret: draft.totpSecret,
        add_attachments: addAttachments,
        remove_attachment_ids: original.attachments.filter((attachment) => !keptIds.has(attachment.id)).map((attachment) => attachment.id),
        restore_history_id: draft.restoreHistoryId,
      });
      setDraft(emptyDraft());
      setOriginal(emptyDraft());
      onDirtyChange?.(false);
      showToast(entry ? t("form.updated") : t("form.added"));
      onDone(true);
    } catch (saveError) {
      let message = String(saveError).replace(/^Error:\s*/, "");
      if (/website rules|HTTP or HTTPS website|twenty websites|Base domain matching/i.test(message)) {
        setShowMore(true);
        if (locale === "zh") message = "请检查网站匹配规则：网址需使用 HTTP 或 HTTPS；基础域名匹配不能用于本机地址或公共后缀。";
      }
      setError(message);
      showToast(message || t("form.saveError"), "error");
    } finally {
      setSaving(false);
    }
  }

  function updateCustomField(id: string, patch: Partial<CustomField>) {
    patchDraft({ customFields: draft.customFields.map((field) => field.clientId === id ? { ...field, ...patch } : field) });
    setAdvancedError("");
  }

  async function saveExistingAttachment(attachment: Attachment) {
    if (!entry) return;
    try {
      const result = await api.downloadAttachment(entry.id, attachment.id);
      downloadAttachment(result.filename, result.mime_type, result.data_b64);
    } catch (downloadError) {
      showToast(String(downloadError).replace(/^Error:\s*/, ""), "error");
    }
  }

  function previewHistoryRestore(previous: Entry, fields: HistoryField[]) {
    const restored = draftFromEntry(previous);
    const mapping = { title: "title", username: "username", password: "password", url: "url", notes: "notes", tags: "tags", entry_type: "entryType", custom_fields: "customFields", totp_secret: "totpSecret", template_data: "templateData", website_rules: "websiteRules" } as const;
    setDraft(current => ({ ...current, ...Object.fromEntries(fields.map(field => [mapping[field], restored[mapping[field]]])), restoreHistoryId: historyToRestore }));
    setShowMore(false);
    showToast(text.loadedDraft);
    setHistoryToRestore(null);
  }

  if (loading) return <div className="loading-state">{t("form.loading")}</div>;

  return (
    <div className="card entry-editor-card">
      {showGenerationHistory && <GenerationHistory onClose={() => setShowGenerationHistory(false)} onUse={password => patchDraft({ password })} />}
      <h2>{heading()}</h2>
      <form onSubmit={handleSave} aria-busy={saving}>
        {!isEdit && (
          <div className="field">
            <label className="field-label" htmlFor="entry-type">{text.type}</label>
            <select
              id="entry-type"
              value={draft.entryType}
              onChange={(event) => patchDraft({ entryType: event.target.value as EntryType })}
            >
              {SUPPORTED_NEW_TYPES.filter(type => personalReady || ["login", "secure_note"].includes(type)).map((type) => <option key={type} value={type}>{entryTypeLabel(type)}</option>)}
            </select>
          </div>
        )}

        {isCompatibility && (
          <div className="context-notice context-notice-warning" role="status">
            <div>
              <strong>{entryTypeLabel(draft.entryType)}</strong>
              <p className="field-hint">{text.compatibilityHint}</p>
            </div>
          </div>
        )}

        <div className="field">
          <label className="field-label" htmlFor="entry-title">{isSecureNote ? text.noteTitle : isTemplate ? (locale === "zh" ? "名称" : "Name") : text.websiteName}</label>
          <input id="entry-title" value={draft.title} onChange={(event) => patchDraft({ title: event.target.value })} required placeholder={t("form.titlePlaceholder")} />
        </div>

        {!isSecureNote && (
          <>
            <div className="field">
              <label className="field-label" htmlFor="entry-username">{t("form.username")}</label>
              <input id="entry-username" value={draft.username} onChange={(event) => patchDraft({ username: event.target.value })} placeholder={t("form.usernamePlaceholder")} autoComplete="off" />
            </div>
            {(draft.entryType !== "recovery_code" || Boolean(draft.password || original.password)) && <PasswordField
              id="entry-password"
              label={draft.entryType === "software_license" ? (locale === "zh" ? "许可证密钥" : "License key") : draft.entryType === "api_credential" ? (locale === "zh" ? "API 令牌或密钥" : "API token or key") : t("form.password")}
              value={draft.password}
              onChange={(password) => patchDraft({ password })}
              hint={isTemplate ? undefined : t("form.passwordHint")}
              required={draft.entryType === "software_license" || draft.entryType === "api_credential"}
              action={draft.entryType === "login" ? <button type="button" className="primary" disabled={generating || saving} onClick={handleGenerate}>{t("form.generate")}</button> : undefined}
            />}
            {draft.entryType === "login" && <>
            <button
              type="button"
              className="ghost compact-disclosure"
              onClick={() => setShowGeneratorOptions((value) => !value)}
              aria-expanded={showGeneratorOptions}
              aria-controls="generator-options"
            >
              {showGeneratorOptions ? text.hideGeneratorOptions : text.generatorOptions}
            </button>
            {personalReady && <button type="button" className="ghost compact-disclosure" onClick={() => setShowGenerationHistory(true)}>{locale === "zh" ? "找回生成的密码" : "Recover a generated password"}</button>}
            {showGeneratorOptions && <GeneratorOptions value={generationOptions} onChange={setGenerationOptions} historyEnabled={personalReady} />}
            </>}
            <div className="field">
              <label className="field-label" htmlFor="entry-url">{text.website}</label>
              <input id="entry-url" type="url" value={draft.url} onChange={(event) => patchDraft({ url: event.target.value })} placeholder="https://" />
            </div>
          </>
        )}

        {(isTemplate || Object.values(draft.templateData).some(value => Array.isArray(value) ? value.length : Boolean(value))) && <CredentialTemplateFields type={draft.entryType} value={draft.templateData} onChange={templateData => patchDraft({ templateData })} saved={entry ? { ...entry, template_data: original.templateData } : null} />}

        <div className="field">
          <label className="field-label" htmlFor="entry-notes">{t("form.notes")}</label>
          <textarea id="entry-notes" value={draft.notes} onChange={(event) => patchDraft({ notes: event.target.value })} rows={isSecureNote ? 10 : 4} placeholder={t("form.notesPlaceholder")} />
        </div>

        <div className="more-options-heading">
          <button
            type="button"
            className="secondary"
            onClick={() => setShowMore((value) => !value)}
            aria-expanded={showMore}
            aria-controls="entry-more-options"
          >
            {showMore ? text.less : text.more}
          </button>
          {!showMore && (
            <p className="field-hint">
              {advancedSummary.length ? interpolate(text.existingSummary, { summary: advancedSummary.join(" · ") }) : text.noAdvanced}
            </p>
          )}
        </div>

        {showMore && (
          <div id="entry-more-options" className="entry-more-options">
            {personalReady && (draft.entryType === "login" || draft.websiteRules.match !== "exact" || draft.websiteRules.additional_urls.length > 0 || draft.websiteRules.excluded_urls.length > 0) && <WebsiteRulesEditor primaryUrl={draft.url} value={draft.websiteRules} onChange={websiteRules => patchDraft({ websiteRules })} />}
            {advancedError && <div className="error" role="alert" id="entry-advanced-error" tabIndex={-1}>{advancedError}</div>}

            <section className="settings-section" aria-labelledby="entry-tags-heading">
              <h3 id="entry-tags-heading" className="section-title">{text.tags}</h3>
              {draft.tags.length > 0 && (
                <ul className="tag-editor-list" aria-label={text.tags}>
                  {draft.tags.map((tag) => (
                    <li key={tag}>
                      <span>{tag}</span>
                      <button
                        type="button"
                        className="ghost"
                        aria-label={interpolate(text.removeTag, { tag })}
                        onClick={() => patchDraft({ tags: draft.tags.filter((item) => item !== tag) })}
                      >
                        ×
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <div className="input-row">
                <label className="sr-only" htmlFor="entry-tag-input">{text.tagInput}</label>
                <input
                  id="entry-tag-input"
                  value={tagInput}
                  onChange={(event) => setTagInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === ",") {
                      event.preventDefault();
                      addTag();
                    }
                  }}
                  placeholder={text.tagPlaceholder}
                  autoComplete="off"
                />
                <button type="button" className="secondary" onClick={addTag} disabled={!tagInput.trim()}>{text.addTag}</button>
              </div>
            </section>

            <TotpEditor value={draft.totpSecret} onChange={totpSecret => patchDraft({ totpSecret })} savedValue={original.totpSecret} entryId={entry?.id} />

            <section className="settings-section" aria-labelledby="custom-fields-heading">
              <h3 id="custom-fields-heading" className="section-title">{text.customFields}</h3>
              {draft.customFields.map((field) => (
                <div className="custom-field-editor" key={field.clientId}>
                  <div className="field">
                    <label className="field-label" htmlFor={`custom-label-${field.clientId}`}>{text.fieldLabel}</label>
                    <input id={`custom-label-${field.clientId}`} value={field.label} onChange={(event) => updateCustomField(field.clientId, { label: event.target.value })} aria-invalid={!field.label.trim() && Boolean(advancedError)} />
                  </div>
                  <div className="field">
                    <label className="field-label" htmlFor={`custom-value-${field.clientId}`}>{text.fieldValue}</label>
                    <input id={`custom-value-${field.clientId}`} type={field.concealed ? "password" : "text"} value={field.value} onChange={(event) => updateCustomField(field.clientId, { value: event.target.value })} autoComplete="off" />
                  </div>
                  <label className="checkbox-field">
                    <input type="checkbox" checked={field.concealed} onChange={(event) => updateCustomField(field.clientId, { concealed: event.target.checked })} />
                    <span>{text.conceal}</span>
                  </label>
                  <button type="button" className="secondary" onClick={() => patchDraft({ customFields: draft.customFields.filter((item) => item.clientId !== field.clientId) })}>{text.remove}</button>
                </div>
              ))}
              <button type="button" className="secondary" onClick={() => patchDraft({ customFields: [...draft.customFields, { clientId: clientId(), label: "", value: "", concealed: false }] })} disabled={draft.customFields.length >= 32}>{text.addField}</button>
            </section>

            <section className="settings-section" aria-labelledby="attachments-heading">
              <h3 id="attachments-heading" className="section-title">{text.attachments}</h3>
              <p className="field-hint">{text.attachmentHint}</p>
              {draft.attachments.map((attachment) => (
                <div className="attachment-row" key={attachment.id}>
                  <span>{attachment.filename} ({Math.ceil(attachment.size / 1024)} KiB)</span>
                  <div className="button-row">
                    <button type="button" className="secondary" onClick={() => saveExistingAttachment(attachment)}>{text.download}</button>
                    <button type="button" className="secondary" onClick={() => patchDraft({ attachments: draft.attachments.filter((item) => item.id !== attachment.id) })}>{text.removeOnSave}</button>
                  </div>
                </div>
              ))}
              {draft.pendingAttachments.map(({ clientId: id, file }) => (
                <div className="attachment-row" key={id}>
                  <span>{file.name} ({Math.ceil(file.size / 1024)} KiB)</span>
                  <button type="button" className="secondary" onClick={() => patchDraft({ pendingAttachments: draft.pendingAttachments.filter((item) => item.clientId !== id) })}>{text.removePending}</button>
                </div>
              ))}
              <label className="secondary file-button" htmlFor="entry-attachments">{text.chooseAttachments}</label>
              <input className="sr-only" id="entry-attachments" type="file" multiple onChange={(event) => {
                const additions = Array.from(event.target.files || []).map((file) => ({ clientId: clientId(), file }));
                patchDraft({ pendingAttachments: [...draft.pendingAttachments, ...additions] });
                event.target.value = "";
              }} />
            </section>

            {entry && (
              <section className="settings-section" aria-labelledby="history-heading">
                <h3 id="history-heading" className="section-title">{text.history}</h3>
                {history.length === 0 ? <p className="field-hint">{text.noHistory}</p> : history.map((item) => (
                  <div className="attachment-row" key={item.id}>
                    <span>{new Date(item.saved_at).toLocaleString()}</span>
                    <button type="button" className="secondary" onClick={() => setHistoryToRestore(item.id)}>{text.previewHistory}</button>
                  </div>
                ))}
              </section>
            )}

            {entry && (
              <section className="settings-section" aria-labelledby="entry-technical-heading">
                <h3 id="entry-technical-heading" className="section-title">{text.technical}</h3>
                <button type="button" className="ghost" onClick={() => setShowTechnical((value) => !value)} aria-expanded={showTechnical} aria-controls="entry-technical-details">
                  {showTechnical ? text.hideTechnical : text.technical}
                </button>
                {showTechnical && (
                  <dl className="status-grid" id="entry-technical-details">
                    <div className="status-row"><dt>{text.source}</dt><dd>{entry.source}</dd></div>
                    <div className="status-row"><dt>{text.syncState}</dt><dd>{entry.sync_status}</dd></div>
                    <div className="status-row"><dt>{text.linkedServices}</dt><dd>{Object.keys(entry.linked_sources || {}).join(", ") || text.none}</dd></div>
                  </dl>
                )}
              </section>
            )}
          </div>
        )}

        {error && <div className="error" role="alert" id="entry-form-error">{error}</div>}
        <div className="button-row entry-editor-actions">
          <button className="primary" type="submit" disabled={saving}>{saving ? t("form.saving") : t("form.save")}</button>
          <button className="secondary" type="button" onClick={() => onDone()} disabled={saving}>{t("form.cancel")}</button>
        </div>
      </form>
      {entry && historyToRestore && <HistoryReview entryId={entry.id} historyId={historyToRestore}
        current={{ title: draft.title, username: draft.username, password: draft.password, url: draft.url, notes: draft.notes, tags: draft.tags, entry_type: draft.entryType, custom_fields: draft.customFields.map(({ label, value, concealed }) => ({ label, value, concealed })), totp_secret: draft.totpSecret, template_data: draft.templateData, website_rules: draft.websiteRules }}
        onRestore={previewHistoryRestore} onCancel={() => setHistoryToRestore(null)} />}
    </div>
  );
}
