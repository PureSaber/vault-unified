import { useEffect, useMemo, useRef, useState } from "react";
import { api, Entry, type OrganizationAction, type OrganizationChange, type OrganizationPreview } from "../api/client";
import { useI18n } from "../i18n";
import { useToast } from "../components/Toast";
import LoadingSkeleton from "../components/LoadingSkeleton";
import ConfirmDialog from "../components/ConfirmDialog";
import DuplicateMerge from "../components/DuplicateMerge";

interface Props {
  onAdd: () => void;
  onImport: () => void;
  onEdit: (entry: Entry) => void;
}

function maskPassword(hasPassword: boolean) {
  return hasPassword ? "••••••••" : "—";
}

export default function VaultList({ onAdd, onEdit, onImport }: Props) {
  const { t, locale } = useI18n();
  const { showToast } = useToast();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [query, setQuery] = useState("");
  const zh = locale === "zh";
  const [state, setState] = useState("active");
  const [personalReady, setPersonalReady] = useState(false);
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [duplicatesOnly, setDuplicatesOnly] = useState(false);
  const [duplicateIds, setDuplicateIds] = useState<string[]>([]);
  const [mergeIds, setMergeIds] = useState<[string, string] | null>(null);
  const [tag, setTag] = useState("");
  const [entryType, setEntryType] = useState("");
  const [sort, setSort] = useState("title");
  const [selected, setSelected] = useState<string[]>([]);
  const [bulkTags, setBulkTags] = useState("");
  const [busy, setBusy] = useState(false);
  const [organizationPlan, setOrganizationPlan] = useState<{ change: OrganizationChange; preview: OrganizationPreview } | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revealedPasswords, setRevealedPasswords] = useState<Record<string, string>>({});
  const [pendingDelete, setPendingDelete] = useState<{ id: string; title: string } | null>(null);
  const debounceRef = useRef<number | null>(null);
  const requestSequence = useRef(0);
  const revealTimers = useRef(new Map<string, number>());
  const criteriaRef = useRef({ query, state, duplicatesOnly });
  criteriaRef.current = { query, state, duplicatesOnly };

  async function load() {
    const sequence = ++requestSequence.current;
    const criteria = criteriaRef.current;
    try {
      setError("");
      setLoading(true);
      const [nextEntries, duplicates] = await Promise.all([api.listEntries(criteria.query.trim() || undefined, criteria.state), criteria.duplicatesOnly ? api.duplicateGroups() : Promise.resolve(null)]);
      if (sequence !== requestSequence.current || criteria.query !== criteriaRef.current.query || criteria.state !== criteriaRef.current.state || criteria.duplicatesOnly !== criteriaRef.current.duplicatesOnly) return;
      setEntries(nextEntries);
      setDuplicateIds(duplicates?.groups.flat() || []);
      setSelected([]);
    } catch (err) {
      if (sequence !== requestSequence.current) return;
      setError(String(err).replace(/^Error:\s*/, ""));
    } finally {
      if (sequence === requestSequence.current) setLoading(false);
    }
  }

  function hideAllPasswords() {
    for (const timer of revealTimers.current.values()) window.clearTimeout(timer);
    revealTimers.current.clear();
    setRevealedPasswords({});
  }

  useEffect(() => {
    void load();
    void api.payloadFormat().then(data => setPersonalReady(data.version >= 3)).catch(() => {});
  }, []);

  const initialSearch = useRef(true);
  useEffect(() => {
    if (initialSearch.current) {
      initialSearch.current = false;
      return;
    }
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      void load();
    }, 250);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  }, [query, state, duplicatesOnly]);

  useEffect(() => {
    const handleBlur = () => hideAllPasswords();
    const handleVisibility = () => {
      if (document.visibilityState !== "visible") hideAllPasswords();
    };
    window.addEventListener("blur", handleBlur);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      window.removeEventListener("blur", handleBlur);
      document.removeEventListener("visibilitychange", handleVisibility);
      for (const timer of revealTimers.current.values()) window.clearTimeout(timer);
      revealTimers.current.clear();
    };
  }, []);

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return entries.filter((entry) =>
      (!duplicatesOnly || duplicateIds.includes(entry.id)) && (!favoritesOnly || entry.favorite) && (!tag || entry.tags.includes(tag)) && (!entryType || entry.entry_type === entryType) &&
      [entry.title, entry.username, entry.url, ...(entry.tags || [])]
        .join(" ")
        .toLowerCase()
        .includes(normalized),
    ).sort((a, b) => sort === "updated" ? b.updated_at.localeCompare(a.updated_at) : sort === "created" ? b.created_at.localeCompare(a.created_at) : a.title.localeCompare(b.title));
  }, [entries, query, favoritesOnly, duplicatesOnly, duplicateIds, tag, entryType, sort]);
  const hasFilters = Boolean(query || favoritesOnly || duplicatesOnly || tag || entryType || state !== "active");

  const actionLabel = (action: OrganizationAction) => ({
    trash: zh ? "移到回收站" : "Move to trash", archive: zh ? "归档" : "Archive",
    restore: zh ? "恢复到密码库" : "Restore to vault", purge: zh ? "永久删除" : "Delete permanently",
    favorite: zh ? "收藏" : "Favorite", unfavorite: zh ? "取消收藏" : "Unfavorite", tag: zh ? "添加标签" : "Add tags",
  })[action];
  const typeLabel = (type: Entry["entry_type"]) => ({ login: zh ? "账号" : "Login", secure_note: zh ? "安全笔记" : "Secure note", card: zh ? "卡片" : "Card", identity: zh ? "身份信息" : "Identity", ssh_key: zh ? "SSH 密钥" : "SSH key", recovery_code: zh ? "恢复码" : "Recovery codes", software_license: zh ? "软件许可证" : "Software license", api_credential: zh ? "API 凭据" : "API credential" })[type];
  async function organize(action: OrganizationAction, ids = selected, immediate = false) {
    if (!ids.length || busy) return;
    setBusy(true);
    const change: OrganizationChange = { action, entry_ids: ids, tags: action === "tag" ? bulkTags.split(/[,，]/).map(value => value.trim()).filter(Boolean) : [] };
    try {
      const preview = await api.previewOrganization(change);
      if (immediate) { await api.applyOrganization(change, preview.preview_token); await load(); }
      else setOrganizationPlan({ change, preview });
    } catch (err) { showToast(String(err).replace(/^Error:\s*/, ""), "error"); }
    finally { setBusy(false); }
  }
  async function applyOrganization() {
    if (!organizationPlan || busy) return;
    const plan = organizationPlan;
    setOrganizationPlan(null); setBusy(true);
    try {
      await api.applyOrganization(plan.change, plan.preview.preview_token);
      hideAllPasswords(); await load();
      showToast(zh ? "整理完成" : "Organization completed");
    } catch (err) { showToast(String(err).replace(/^Error:\s*/, ""), "error"); }
    finally { setBusy(false); }
  }
  function cancelOrganization() {
    if (organizationPlan) void api.cancelOrganization(organizationPlan.preview.preview_token).catch(() => {});
    setOrganizationPlan(null);
  }

  async function toggleReveal(id: string) {
    if (revealedPasswords[id] != null) {
      hideAllPasswords();
      return;
    }
    try {
      const entry = await api.getEntry(id, true);
      hideAllPasswords();
      setRevealedPasswords({ [id]: entry.password || "" });
      const timer = window.setTimeout(() => {
        setRevealedPasswords((previous) => {
          const next = { ...previous };
          delete next[id];
          return next;
        });
        revealTimers.current.delete(id);
      }, 30_000);
      revealTimers.current.set(id, timer);
    } catch (err) {
      showToast(String(err).replace(/^Error:\s*/, ""), "error");
    }
  }

  async function handleCopy(id: string) {
    try {
      await api.copy(id);
      showToast(t("list.copiedPass"));
    } catch (err) {
      showToast(String(err).replace(/^Error:\s*/, ""), "error");
    }
  }

  async function handleCopyUsername(id: string) {
    try {
      await api.copy(id, "username");
      showToast(t("list.copiedUser"));
    } catch (err) {
      showToast(String(err).replace(/^Error:\s*/, ""), "error");
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    const { id } = pendingDelete;
    setPendingDelete(null);
    try {
      await api.deleteEntry(id);
      showToast(t("list.deleted"));
      void load();
    } catch (err) {
      showToast(String(err).replace(/^Error:\s*/, ""), "error");
    }
  }

  return (
    <div>
      {mergeIds && <DuplicateMerge ids={mergeIds} onCancel={() => setMergeIds(null)} onMerged={() => { setMergeIds(null); hideAllPasswords(); void load(); showToast(zh ? "账号已合并，被合并条目可在回收站恢复" : "Accounts merged; the second account can be restored from trash"); }} />}
      <ConfirmDialog open={organizationPlan !== null} idPrefix="organization"
        title={organizationPlan ? actionLabel(organizationPlan.change.action) : ""}
        message={organizationPlan ? `${zh ? "选中条目" : "Selected entries"}: ${organizationPlan.preview.entries.map(entry => entry.title).join("、")}\n${organizationPlan.change.action === "trash" ? (zh ? "回收站保留 30 天，到期自动清理；期间可恢复。" : "Trash keeps items for 30 days, then removes them automatically. Restore them during this period.") : organizationPlan.change.action === "purge" ? (zh ? "将从回收站永久删除这些条目。" : "These items will be permanently removed from trash.") : ""}` : ""}
        confirmLabel={organizationPlan ? actionLabel(organizationPlan.change.action) : ""}
        variant={organizationPlan?.change.action === "purge" ? "danger" : "default"}
        onConfirm={() => void applyOrganization()} onCancel={cancelOrganization} />
      <ConfirmDialog
        open={pendingDelete !== null}
        title={t("list.deleteTitle")}
        message={pendingDelete ? t("list.deleteMessage", { title: pendingDelete.title }) : ""}
        confirmLabel={t("list.delete")}
        variant="danger"
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />

      <div className="page-heading-row">
        <div>
          <h2>{t("list.title")}</h2>
          <p className="field-hint">{t("list.subtitle")}</p>
        </div>
        <div className="button-row">
        <button className="secondary" type="button" onClick={onImport}>
          {locale === "zh" ? "从浏览器导入" : "Import from browser"}
        </button>
        <button className="primary" type="button" onClick={onAdd}>
          {t("list.addPassword")}
        </button>
        </div>
      </div>

      <div className="list-toolbar">
        <input
          id="vault-search"
          placeholder={t("list.searchPlaceholder")}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label={t("list.searchAria")}
        />
        {personalReady && <select aria-label={zh ? "条目位置" : "Entry location"} value={state} onChange={event => { hideAllPasswords(); ++requestSequence.current; setEntries([]); setSelected([]); setDuplicatesOnly(false); setLoading(true); setState(event.target.value); }}>
          <option value="active">{zh ? "密码库" : "Vault"}</option>
          <option value="archived">{zh ? "归档" : "Archived"}</option>
          <option value="trash">{zh ? "回收站" : "Trash"}</option>
        </select>}
      </div>

      {personalReady && <details className="card" aria-label={zh ? "筛选与批量整理" : "Filters and bulk organization"}>
        <summary>{zh ? "筛选与批量整理" : "Filters and bulk organization"}{selected.length ? ` (${selected.length})` : ""}</summary>
        <div className="button-row">
          <label className="organization-favorite-filter"><input type="checkbox" checked={favoritesOnly} onChange={event => setFavoritesOnly(event.target.checked)} />{zh ? "仅收藏" : "Favorites only"}</label>
          {state === "active" && <label className="organization-favorite-filter"><input type="checkbox" checked={duplicatesOnly} onChange={event => { setSelected([]); setDuplicatesOnly(event.target.checked); }} />{zh ? "仅重复账号" : "Duplicates only"}</label>}
          <label>{zh ? "标签" : "Tag"}<select value={tag} onChange={event => setTag(event.target.value)}><option value="">{zh ? "全部标签" : "All tags"}</option>{[...new Set(entries.flatMap(entry => entry.tags))].sort().map(value => <option key={value}>{value}</option>)}</select></label>
          <label>{zh ? "类型" : "Type"}<select value={entryType} onChange={event => setEntryType(event.target.value)}><option value="">{zh ? "全部类型" : "All types"}</option>{[...new Set(entries.map(entry => entry.entry_type))].sort().map(value => <option key={value} value={value}>{typeLabel(value)}</option>)}</select></label>
          <label>{zh ? "排序" : "Sort"}<select value={sort} onChange={event => setSort(event.target.value)}><option value="title">{zh ? "名称" : "Name"}</option><option value="updated">{zh ? "最近修改" : "Recently changed"}</option><option value="created">{zh ? "最近添加" : "Recently added"}</option></select></label>
        </div>
        <div className="button-row">
          <button type="button" className="secondary" onClick={() => setSelected(selected.length ? [] : filtered.slice(0, 500).map(entry => entry.id))}>{selected.length ? (zh ? "取消选择" : "Clear selection") : (zh ? "选择当前列表" : "Select current list")}</button>
          {state === "active" && <button type="button" className="secondary" disabled={selected.length !== 2 || busy} onClick={() => { hideAllPasswords(); setMergeIds([selected[0], selected[1]]); }}>{zh ? "比较并合并" : "Compare and merge"}</button>}
          {(state === "trash" ? ["restore", "purge"] as OrganizationAction[] : state === "archived" ? ["restore", "trash"] as OrganizationAction[] : ["archive", "trash"] as OrganizationAction[]).map(action => <button key={action} type="button" className={action === "purge" ? "danger" : "secondary"} disabled={!selected.length || busy} onClick={() => void organize(action)}>{actionLabel(action)}</button>)}
          <input aria-label={zh ? "批量添加的标签" : "Tags to add"} placeholder={zh ? "用逗号分隔标签" : "Comma-separated tags"} value={bulkTags} onChange={event => setBulkTags(event.target.value)} />
          <button type="button" className="secondary" disabled={!selected.length || !bulkTags.trim() || busy} onClick={() => void organize("tag")}>{actionLabel("tag")}</button>
        </div>
      </details>}
      {personalReady && state === "trash" && <p className="field-hint">{zh ? "回收站保留 30 天，到期自动清理。回收站和归档中的账号不会出现在浏览器填充建议中。" : "Trash keeps items for 30 days, then removes them automatically. Trash and archived accounts do not appear in browser fill suggestions."}</p>}
      {!personalReady && <p className="field-hint">{zh ? "在“安全与恢复”中升级密码库，即可启用收藏、归档和回收站。" : "Upgrade the vault in Security & recovery to enable favorites, archive and trash."}</p>}

      {error && <div className="error" role="alert">{error}</div>}

      {loading && !error ? (
        <LoadingSkeleton />
      ) : filtered.length === 0 && !error ? (
        <div className="empty-state card">
          <p className="empty-state-title">{hasFilters ? t("list.noResults") : t("list.emptyTitle")}</p>
          <p className="empty-state-hint">{hasFilters ? t("list.noResultsHint") : t("list.emptyHint")}</p>
          {!hasFilters && (
            <button className="primary" type="button" onClick={onAdd}>
              {t("list.addFirstPassword")}
            </button>
          )}
        </div>
      ) : (
        <ul className="entry-list" aria-label={t("list.entriesAria")}>
          {filtered.map((entry) => {
            const revealed = revealedPasswords[entry.id] != null;
            return (
              <li className={`entry-row${personalReady ? " entry-row-selectable" : ""}`} key={entry.id}>
                {personalReady && <input type="checkbox" aria-label={`${zh ? "选择" : "Select"} ${entry.title}`} checked={selected.includes(entry.id)} disabled={busy} onChange={event => setSelected(current => event.target.checked ? [...current, entry.id] : current.filter(id => id !== entry.id))} />}
                <button
                  type="button"
                  className="entry-open"
                  onClick={() => onEdit(entry)}
                  aria-label={t("list.openEntry", { title: entry.title })}
                >
                  <span className="entry-title">{entry.title}</span>
                  {entry.favorite && <span aria-label={zh ? "已收藏" : "Favorite"}>★</span>}
                  <span className="entry-meta">
                    <span className="entry-username">{entry.username || t("list.noUsername")}</span>
                    <span className="entry-password-preview" aria-label={t("list.passwordAria")}>
                      {revealed ? revealedPasswords[entry.id] || "—" : maskPassword(entry.has_password)}
                    </span>
                    {entry.sync_status === "dirty" && (
                      <span className="badge badge-sync-dirty">{t("list.waitingSync")}</span>
                    )}
                    {entry.sync_status === "conflict" && (
                      <span className="badge badge-sync-conflict">{t("list.changedBothPlaces")}</span>
                    )}
                  </span>
                  {entry.tags?.length > 0 && (
                    <span className="entry-chips">
                      {entry.tags.map((tag) => <span className="chip" key={`tag-${tag}`}>{tag}</span>)}
                    </span>
                  )}
                </button>
                <div className="entry-actions">
                  <button type="button" className="primary" onClick={() => entry.entry_type === "recovery_code" ? onEdit(entry) : void handleCopy(entry.id)}>
                    {entry.entry_type === "recovery_code" ? (zh ? "查看恢复码" : "View recovery codes") : ["software_license", "api_credential"].includes(entry.entry_type) ? (zh ? "复制密钥" : "Copy key") : t("list.copyPass")}
                  </button>
                  <details className="entry-more">
                    <summary>{t("list.moreActions")}</summary>
                    <div className="entry-more-menu">
                      {personalReady && <button type="button" className="ghost" disabled={busy} onClick={() => void organize(entry.favorite ? "unfavorite" : "favorite", [entry.id], true)}>{actionLabel(entry.favorite ? "unfavorite" : "favorite")}</button>}
                      {personalReady && <button type="button" className="ghost" disabled={busy} onClick={() => void organize(state === "active" ? "archive" : "restore", [entry.id])}>{actionLabel(state === "active" ? "archive" : "restore")}</button>}
                      <button type="button" className="ghost" onClick={() => toggleReveal(entry.id)}>
                        {revealed ? t("list.hidePassword") : t("list.showPassword")}
                      </button>
                      <button type="button" className="ghost" onClick={() => handleCopyUsername(entry.id)}>
                        {t("list.copyUser")}
                      </button>
                      <button type="button" className="ghost" onClick={() => onEdit(entry)}>
                        {t("list.edit")}
                      </button>
                      <button
                        type="button"
                        className="danger"
                        disabled={busy}
                        onClick={() => personalReady ? void organize(state === "trash" ? "purge" : "trash", [entry.id]) : setPendingDelete({ id: entry.id, title: entry.title })}
                      >
                        {personalReady ? actionLabel(state === "trash" ? "purge" : "trash") : t("list.delete")}
                      </button>
                    </div>
                  </details>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
