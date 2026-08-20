import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type Locale = "zh" | "en";

type Dict = Record<string, string>;

const zh: Dict = {
  "app.title": "Vault Unified",
  "nav.vault": "保险库",
  "nav.add": "添加",
  "nav.sync": "同步",
  "nav.conflicts": "冲突",
  "nav.settings": "设置",
  "nav.lock": "锁定",
  "nav.main": "主导航",
  "nav.conflictBadge": "{count} 个冲突",
  "lang.zh": "中文",
  "lang.en": "English",
  "lang.label": "语言",

  "unlock.subtitle": "输入主密码以解锁加密保险库。",
  "unlock.password": "主密码",
  "unlock.remember": "在此电脑记住（Windows 凭据管理器）",
  "unlock.submit": "解锁",
  "unlock.unlocking": "解锁中…",
  "unlock.useSaved": "使用已保存密码",
  "unlock.apiUnreachable":
    "无法连接保险库 API。请确认应用已成功启动其安全 sidecar。",

  "list.searchPlaceholder": "按标题、用户名或 URL 搜索…",
  "list.search": "搜索",
  "list.searchAria": "搜索保险库",
  "list.emptyTitle": "保险库为空",
  "list.emptyHint": "手动添加凭据，或运行同步从 Proton Pass / Bitwarden 拉取条目。",
  "list.noUsername": "无用户名",
  "list.show": "显示",
  "list.hide": "隐藏",
  "list.showPassword": "显示密码",
  "list.hidePassword": "隐藏密码",
  "list.copyPass": "复制密码",
  "list.copyUser": "复制用户名",
  "list.edit": "编辑",
  "list.delete": "删除",
  "list.deleteTitle": "删除条目",
  "list.deleteMessage": "确定删除「{title}」？此操作无法从界面撤销。",
  "list.copiedPass": "密码已复制到剪贴板",
  "list.copiedUser": "用户名已复制到剪贴板",
  "list.deleted": "条目已删除",
  "list.entriesAria": "保险库条目",
  "list.passwordAria": "密码",
  "list.conflictChip": "冲突",
  "list.tags": "标签",
  "list.linked": "已关联",

  "form.add": "添加条目",
  "form.edit": "编辑条目",
  "form.loading": "加载条目…",
  "form.title": "标题",
  "form.titlePlaceholder": "例如 GitHub",
  "form.username": "用户名",
  "form.usernamePlaceholder": "邮箱或用户名",
  "form.password": "密码",
  "form.passwordHint": "默认遮罩。使用生成获得强随机密码。",
  "form.generate": "生成密码",
  "form.genLength": "长度",
  "form.genSymbols": "包含符号",
  "form.generated": "已生成密码",
  "form.url": "URL",
  "form.notes": "备注",
  "form.notesPlaceholder": "可选备注",
  "form.save": "保存",
  "form.saving": "保存中…",
  "form.cancel": "取消",
  "form.updated": "条目已更新",
  "form.added": "条目已添加",
  "form.saveError": "保存失败",

  "settings.title": "设置",
  "settings.loading": "加载设置…",
  "settings.loadError": "无法加载设置",
  "settings.retry": "重试",
  "settings.enabledSources": "启用的外部源",
  "settings.enabledHint":
    "仅勾选的源参与同步。取消勾选的源保留本地关联，但停止拉取/推送。",
  "settings.resetSources": "重置为全部源",
  "settings.resetSourcesHint": "将 enabled_sources 设为 null（启用全部源）",
  "settings.syncBehavior": "同步行为",
  "settings.primary": "主数据源",
  "settings.primaryLocal": "本地保险库（默认）",
  "settings.primaryHint":
    "主源上的日常编辑在冲突时默认优先。本地为主时可在编辑时自动推送。",
  "settings.conflictDefault": "冲突默认策略",
  "settings.conflictPrimary": "跟随主源（primary）",
  "settings.conflictManual": "始终手动处理（manual）",
  "settings.autoPush": "编辑时自动推送到云端（主源为本地时）",
  "settings.autoPull": "同步时自动从云端拉取",
  "settings.proton": "Proton Pass",
  "settings.protonVault": "保险库名称",
  "settings.protonVaultPlaceholder": "可选默认保险库",
  "settings.protonShare": "Share ID",
  "settings.protonSharePlaceholder": "推送到 Proton 时需要",
  "settings.sourceStatus": "源状态提示",
  "settings.configureHint": "请通过 .env / 安装脚本配置",
  "settings.language": "界面语言",
  "settings.save": "保存设置",
  "settings.saving": "保存中…",
  "settings.saved": "设置已保存",

  "sync.title": "同步",
  "sync.hint": "与已启用的外部源拉取与推送。在设置中配置激活的源。",
  "sync.connectionStatus": "连接状态",
  "sync.loadingStatus": "加载状态…",
  "sync.bidirectional": "双向同步",
  "sync.syncing": "同步中…",
  "sync.pushDirty": "推送脏条目",
  "sync.pushing": "推送中…",
  "sync.pull": "拉取",
  "sync.pulling": "拉取中…",
  "sync.pullSource": "从 {source} 拉取",
  "sync.lastOp": "上次操作",
  "sync.completed": "同步完成",
  "sync.pushCompleted": "推送完成",
  "sync.pullCompleted": "拉取完成",
  "sync.viewConflicts": "查看冲突（{count}）",
  "sync.perSource": "按源拉取",

  "conflicts.title": "冲突",
  "conflicts.loading": "加载冲突…",
  "conflicts.empty": "无冲突。所有条目已与主源同步。",
  "conflicts.hint":
    "高亮字段表示本地与远程不一致。默认选项跟随主源设置。",
  "conflicts.showPasswords": "显示密码",
  "conflicts.hidePasswords": "隐藏密码",
  "conflicts.local": "本地保险库",
  "conflicts.recommended": "（推荐）",
  "conflicts.keepLocal": "保留本地",
  "conflicts.useRemote": "使用远程",
  "conflicts.resolveMerge": "按字段合并并解决",
  "conflicts.pickLocal": "本地",
  "conflicts.pickRemote": "远程",
  "conflicts.fieldPick": "按字段选择",
  "conflicts.resolved": "冲突已解决（{choice}）",
  "conflicts.resolving": "处理中…",

  "confirm.confirm": "确认",
  "confirm.cancel": "取消",

  "toast.defaultError": "出错了",

  "common.loading": "加载中…",
  "skip.main": "跳到主内容",

  "syncSummary.pulled": "拉取",
  "syncSummary.pushed": "推送",
  "syncSummary.conflicts": "冲突",
  "syncSummary.errors": "错误",
  "syncSummary.none": "无",
  "syncSummary.noPush": "未推送条目",
  "syncSummary.noChanges": "无变更",
  "syncSummary.unresolved": "{count} 未解决",
  "syncSummary.showRaw": "显示技术细节",
  "syncSummary.hideRaw": "隐藏技术细节",
  "syncSummary.rawAria": "原始同步响应",
};

const en: Dict = {
  "app.title": "Vault Unified",
  "nav.vault": "Vault",
  "nav.add": "Add",
  "nav.sync": "Sync",
  "nav.conflicts": "Conflicts",
  "nav.settings": "Settings",
  "nav.lock": "Lock",
  "nav.main": "Main navigation",
  "nav.conflictBadge": "{count} conflicts",
  "lang.zh": "中文",
  "lang.en": "English",
  "lang.label": "Language",

  "unlock.subtitle": "Enter your master password to unlock the encrypted vault.",
  "unlock.password": "Master password",
  "unlock.remember": "Remember on this PC (Windows Credential Manager)",
  "unlock.submit": "Unlock",
  "unlock.unlocking": "Unlocking…",
  "unlock.useSaved": "Use saved password",
  "unlock.apiUnreachable":
    "Cannot reach the vault API. Ensure the app started its secure sidecar.",

  "list.searchPlaceholder": "Search by title, username, or URL…",
  "list.search": "Search",
  "list.searchAria": "Search vault",
  "list.emptyTitle": "Your vault is empty",
  "list.emptyHint":
    "Add a credential manually or run sync to pull entries from Proton Pass or Bitwarden.",
  "list.noUsername": "No username",
  "list.show": "Show",
  "list.hide": "Hide",
  "list.showPassword": "Show password",
  "list.hidePassword": "Hide password",
  "list.copyPass": "Copy pass",
  "list.copyUser": "Copy user",
  "list.edit": "Edit",
  "list.delete": "Delete",
  "list.deleteTitle": "Delete entry",
  "list.deleteMessage":
    'Delete "{title}"? This cannot be undone from the vault UI.',
  "list.copiedPass": "Password copied to clipboard",
  "list.copiedUser": "Username copied to clipboard",
  "list.deleted": "Entry deleted",
  "list.entriesAria": "Vault entries",
  "list.passwordAria": "Password",
  "list.conflictChip": "Conflict",
  "list.tags": "Tags",
  "list.linked": "Linked",

  "form.add": "Add entry",
  "form.edit": "Edit entry",
  "form.loading": "Loading entry…",
  "form.title": "Title",
  "form.titlePlaceholder": "e.g. GitHub",
  "form.username": "Username",
  "form.usernamePlaceholder": "email or username",
  "form.password": "Password",
  "form.passwordHint": "Masked by default. Use Generate for a strong random password.",
  "form.generate": "Generate password",
  "form.genLength": "Length",
  "form.genSymbols": "Include symbols",
  "form.generated": "Password generated",
  "form.url": "URL",
  "form.notes": "Notes",
  "form.notesPlaceholder": "Optional notes",
  "form.save": "Save",
  "form.saving": "Saving…",
  "form.cancel": "Cancel",
  "form.updated": "Entry updated",
  "form.added": "Entry added",
  "form.saveError": "Save failed",

  "settings.title": "Settings",
  "settings.loading": "Loading settings…",
  "settings.loadError": "Could not load settings",
  "settings.retry": "Retry",
  "settings.enabledSources": "Enabled external sources",
  "settings.enabledHint":
    "Only checked sources participate in sync. Unchecked sources keep local links but stop pull/push.",
  "settings.resetSources": "Reset to all sources",
  "settings.resetSourcesHint": "Set enabled_sources to null (enable all sources)",
  "settings.syncBehavior": "Sync behavior",
  "settings.primary": "Primary data source",
  "settings.primaryLocal": "Local vault (default)",
  "settings.primaryHint":
    "Daily edits on the primary source win conflicts by default. Local primary enables auto-push on edit.",
  "settings.conflictDefault": "Conflict default",
  "settings.conflictPrimary": "Follow primary (primary)",
  "settings.conflictManual": "Always resolve manually (manual)",
  "settings.autoPush": "Auto-push to cloud when editing (when primary is local)",
  "settings.autoPull": "Auto-pull from cloud on sync",
  "settings.proton": "Proton Pass",
  "settings.protonVault": "Vault name",
  "settings.protonVaultPlaceholder": "Optional default vault",
  "settings.protonShare": "Share ID",
  "settings.protonSharePlaceholder": "Required for push to Proton",
  "settings.sourceStatus": "Source status hints",
  "settings.configureHint": "Configure via .env / setup scripts",
  "settings.language": "Interface language",
  "settings.save": "Save settings",
  "settings.saving": "Saving…",
  "settings.saved": "Settings saved",

  "sync.title": "Sync",
  "sync.hint":
    "Pull from and push to enabled external sources. Configure which sources are active in Settings.",
  "sync.connectionStatus": "Connection status",
  "sync.loadingStatus": "Loading status…",
  "sync.bidirectional": "Bidirectional sync",
  "sync.syncing": "Syncing…",
  "sync.pushDirty": "Push dirty entries",
  "sync.pushing": "Pushing…",
  "sync.pull": "Pull",
  "sync.pulling": "Pulling…",
  "sync.pullSource": "Pull from {source}",
  "sync.lastOp": "Last operation",
  "sync.completed": "Sync completed",
  "sync.pushCompleted": "Push completed",
  "sync.pullCompleted": "Pull completed",
  "sync.viewConflicts": "View conflicts ({count})",
  "sync.perSource": "Per-source pull",

  "conflicts.title": "Conflicts",
  "conflicts.loading": "Loading conflicts…",
  "conflicts.empty": "No conflicts. All entries are in sync with your primary source.",
  "conflicts.hint":
    "Highlighted fields differ between local and remote. Default choice follows your primary source.",
  "conflicts.showPasswords": "Show passwords",
  "conflicts.hidePasswords": "Hide passwords",
  "conflicts.local": "Local vault",
  "conflicts.recommended": " (recommended)",
  "conflicts.keepLocal": "Keep local",
  "conflicts.useRemote": "Use remote",
  "conflicts.resolveMerge": "Merge selected fields",
  "conflicts.pickLocal": "Local",
  "conflicts.pickRemote": "Remote",
  "conflicts.fieldPick": "Field-level pick",
  "conflicts.resolved": "Conflict resolved ({choice})",
  "conflicts.resolving": "Resolving…",

  "confirm.confirm": "Confirm",
  "confirm.cancel": "Cancel",

  "toast.defaultError": "Something went wrong",

  "common.loading": "Loading…",
  "skip.main": "Skip to main content",

  "syncSummary.pulled": "Pulled",
  "syncSummary.pushed": "Pushed",
  "syncSummary.conflicts": "Conflicts",
  "syncSummary.errors": "Errors",
  "syncSummary.none": "None",
  "syncSummary.noPush": "No entries pushed",
  "syncSummary.noChanges": "no changes",
  "syncSummary.unresolved": "{count} unresolved",
  "syncSummary.showRaw": "Show technical details",
  "syncSummary.hideRaw": "Hide technical details",
  "syncSummary.rawAria": "Raw sync response",
};

const LOCALES: Record<Locale, Dict> = { zh, en };

function readStoredLocale(): Locale {
  try {
    const v = localStorage.getItem("vault_locale");
    if (v === "en" || v === "zh") return v;
  } catch {
    /* ignore */
  }
  return "zh";
}

function interpolate(template: string, vars?: Record<string, string | number>) {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (_, key: string) =>
    vars[key] != null ? String(vars[key]) : `{${key}}`
  );
}

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(readStoredLocale);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    try {
      localStorage.setItem("vault_locale", next);
    } catch {
      /* ignore */
    }
  }, []);

  const t = useCallback(
    (key: string, vars?: Record<string, string | number>) => {
      const dict = LOCALES[locale] || zh;
      const raw = dict[key] ?? LOCALES.en[key] ?? key;
      return interpolate(raw, vars);
    },
    [locale]
  );

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}
