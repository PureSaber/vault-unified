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
  "nav.passwords": "密码",
  "nav.securityRecovery": "安全与恢复",
  "nav.connections": "连接",
  "nav.lockNow": "立即锁定",
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
  "unlock.rememberHint":
    "仅在信任这台电脑和当前 Windows 账户时启用。",
  "unlock.submit": "解锁",
  "unlock.unlocking": "解锁中…",
  "unlock.useSaved": "使用已保存密码",
  "unlock.apiUnreachable":
    "无法连接密码库的后台服务。请重新打开应用；如果仍然失败，再查看技术错误详情。",

  "list.title": "密码",
  "list.subtitle": "添加、查找和复制你的账号密码。",
  "list.addPassword": "添加密码",
  "list.addFirstPassword": "添加第一个密码",
  "list.searchPlaceholder": "按标题、用户名或 URL 搜索…",
  "list.search": "搜索",
  "list.searchAria": "搜索保险库",
  "list.emptyTitle": "还没有保存密码",
  "list.emptyHint": "先添加第一个账号；连接外部密码服务是可选的。",
  "list.noResults": "没有找到匹配的密码",
  "list.noResultsHint": "试试账号名称、用户名或网站。",
  "list.noUsername": "无用户名",
  "list.show": "显示",
  "list.hide": "隐藏",
  "list.showPassword": "显示密码",
  "list.hidePassword": "隐藏密码",
  "list.copyPass": "复制密码",
  "list.moreActions": "更多操作",
  "list.openEntry": "打开 {title}",
  "list.waitingSync": "等待同步",
  "list.changedBothPlaces": "两处都发生了修改",
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
  "settings.simpleHint": "只保留常用偏好。备份、恢复和连接设置已放到对应页面。",
  "settings.about": "关于与版本",
  "settings.product": "产品",
  "settings.version": "版本",
  "settings.platform": "支持平台",
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

  "conflicts.contextNotice": "有 {count} 个账号在这台设备和某个已连接服务中都发生了修改，需要处理。",
  "conflicts.review": "处理冲突",
  "conflicts.backToPasswords": "返回密码",
  "security.noBackupReminder": "尚未设置备份。密码仍然可用，但电脑损坏后可能无法恢复。",
  "security.setBackup": "设置备份",

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
  "conflicts.empty": "目前没有需要处理的两处修改。",
  "conflicts.hint":
    "高亮字段在这台设备和已连接服务中不同。请为每个字段选择要保留的版本。",
  "conflicts.showPasswords": "显示密码",
  "conflicts.hidePasswords": "隐藏密码",
  "conflicts.local": "这台设备",
  "conflicts.connectedService": "已连接的服务",
  "conflicts.recommended": "（推荐）",
  "conflicts.keepLocal": "保留这台设备的版本",
  "conflicts.useRemote": "使用已连接服务的版本",
  "conflicts.resolveMerge": "按字段合并并解决",
  "conflicts.pickLocal": "这台设备",
  "conflicts.pickRemote": "已连接服务",
  "conflicts.field.title": "名称",
  "conflicts.field.username": "用户名",
  "conflicts.field.password": "密码",
  "conflicts.field.url": "网站地址",
  "conflicts.field.notes": "备注",
  "conflicts.fieldPick": "按字段选择",
  "conflicts.resolved": "两处修改已处理",
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
  "syncSummary.operationResults": "逐条执行结果",
};

const en: Dict = {
  "app.title": "Vault Unified",
  "nav.passwords": "Passwords",
  "nav.securityRecovery": "Security & recovery",
  "nav.connections": "Connections",
  "nav.lockNow": "Lock now",
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
  "unlock.rememberHint":
    "Enable only on a trusted computer and Windows account.",
  "unlock.submit": "Unlock",
  "unlock.unlocking": "Unlocking…",
  "unlock.useSaved": "Use saved password",
  "unlock.apiUnreachable":
    "Cannot reach the password vault background service. Reopen the app; view technical error details only if the problem continues.",

  "list.title": "Passwords",
  "list.subtitle": "Add, find, and copy passwords for your accounts.",
  "list.addPassword": "Add password",
  "list.addFirstPassword": "Add first password",
  "list.searchPlaceholder": "Search by title, username, or URL…",
  "list.search": "Search",
  "list.searchAria": "Search vault",
  "list.emptyTitle": "Your vault is empty",
  "list.emptyHint": "Add your first account. Connecting an external password service is optional.",
  "list.noResults": "No matching passwords",
  "list.noResultsHint": "Try an account name, username, or website.",
  "list.noUsername": "No username",
  "list.show": "Show",
  "list.hide": "Hide",
  "list.showPassword": "Show password",
  "list.hidePassword": "Hide password",
  "list.copyPass": "Copy password",
  "list.moreActions": "More actions",
  "list.openEntry": "Open {title}",
  "list.waitingSync": "Waiting to sync",
  "list.changedBothPlaces": "Changed in both locations",
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
  "settings.simpleHint": "Only common preferences live here. Backup, recovery, and connections are in their own pages.",
  "settings.about": "About & version",
  "settings.product": "Product",
  "settings.version": "Version",
  "settings.platform": "Supported platform",
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

  "conflicts.contextNotice": "{count} account(s) changed both on this device and in a connected service and need review.",
  "conflicts.review": "Review changes",
  "conflicts.backToPasswords": "Back to passwords",
  "security.noBackupReminder": "Backup has not been set up. Passwords still work, but recovery may be impossible if this computer fails.",
  "security.setBackup": "Set up backup",

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
  "conflicts.empty": "There are no changes from two locations to review.",
  "conflicts.hint":
    "Highlighted fields differ between this device and the connected service. Choose which version to keep for each field.",
  "conflicts.showPasswords": "Show passwords",
  "conflicts.hidePasswords": "Hide passwords",
  "conflicts.local": "This device",
  "conflicts.connectedService": "Connected service",
  "conflicts.recommended": " (recommended)",
  "conflicts.keepLocal": "Keep this device version",
  "conflicts.useRemote": "Use connected service version",
  "conflicts.resolveMerge": "Merge selected fields",
  "conflicts.pickLocal": "This device",
  "conflicts.pickRemote": "Connected service",
  "conflicts.field.title": "Name",
  "conflicts.field.username": "Username",
  "conflicts.field.password": "Password",
  "conflicts.field.url": "Website",
  "conflicts.field.notes": "Notes",
  "conflicts.fieldPick": "Field-level pick",
  "conflicts.resolved": "Changes from both locations were resolved",
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
  "syncSummary.operationResults": "Item-level results",
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
