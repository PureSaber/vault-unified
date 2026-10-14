import packageMetadata from "../../package.json";
import { useState } from "react";
import { useI18n, type Locale } from "../i18n";
import { saveDesktopPreferences, type DesktopPreferences, type DesktopStatus } from "../desktop";
import HelloSettings from "../components/HelloSettings";

export default function Settings({ desktop, onDesktopChange, onExit }: { desktop: DesktopStatus | null; onDesktopChange: (value: DesktopStatus) => void; onExit: () => void }) {
  const { t, locale, setLocale } = useI18n();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const zh = locale === "zh";
  async function update(preferences: DesktopPreferences) {
    setSaving(true); setError("");
    try { onDesktopChange(await saveDesktopPreferences(preferences)); }
    catch (reason) { setError(String(reason).includes("shortcut_unavailable") ? (zh ? "该快捷键已被占用，请选择其他组合。" : "This shortcut is in use. Choose another combination.") : (zh ? "设置未能保存，请重试。" : "Could not save settings. Try again.")); }
    finally { setSaving(false); }
  }

  return (
    <div className="card">
      <h2>{t("settings.title")}</h2>
      <p className="field-hint">{t("settings.simpleHint")}</p>

      <section className="settings-section" aria-labelledby="locale-heading">
        <h3 id="locale-heading" className="section-title">
          {t("settings.language")}
        </h3>
        <div className="field">
          <label className="field-label" htmlFor="settings-locale">
            {t("lang.label")}
          </label>
          <select
            id="settings-locale"
            value={locale}
            onChange={(event) => setLocale(event.target.value as Locale)}
          >
            <option value="zh">{t("lang.zh")}</option>
            <option value="en">{t("lang.en")}</option>
          </select>
        </div>
      </section>

      {desktop && <section className="settings-section" aria-labelledby="desktop-heading">
        <h3 id="desktop-heading" className="section-title">{zh ? "快捷搜索与托盘" : "Quick search and tray"}</h3>
        <p className="field-hint">{zh ? "在任意应用中唤起搜索。窗口内也可使用 Ctrl+K。" : "Open search from any application. Ctrl+K also works inside the window."}</p>
        <div className="field"><label className="field-label" htmlFor="desktop-shortcut">{zh ? "全局快捷键" : "Global shortcut"}</label>
          <select id="desktop-shortcut" disabled={saving} value={desktop.preferences.shortcut} onChange={event => void update({ ...desktop.preferences, shortcut: event.target.value })}>
            <option value="Control+Shift+Space">Ctrl+Shift+Space</option><option value="Control+Alt+KeyV">Ctrl+Alt+V</option><option value="Control+Shift+KeyY">Ctrl+Shift+Y</option><option value="">{zh ? "关闭" : "Off"}</option>
          </select>
        </div>
        {desktop.preferences.shortcut && !desktop.shortcut_registered && <p role="status">{zh ? "当前快捷键不可用，请更换组合。" : "The current shortcut is unavailable. Choose another combination."}</p>}
        <label className="checkbox-label"><input type="checkbox" checked={desktop.preferences.close_to_tray} disabled={saving || !desktop.tray_available} onChange={event => void update({ ...desktop.preferences, close_to_tray: event.target.checked })} />{zh ? "关闭主窗口时收起到托盘" : "Keep running in the tray when the window closes"}</label>
        {!desktop.tray_available && <p role="status">{zh ? "托盘不可用，关闭窗口会退出应用。" : "The tray is unavailable; closing the window quits the app."}</p>}
        <p className="field-hint">{zh ? "收起后仍按设定时间自动锁定。需要完全退出时，使用托盘菜单或下方按钮。" : "Auto-lock stays active while hidden. Use the tray menu or the button below to quit."}</p>
        <p className="field-hint">{zh ? "Windows 锁屏或休眠会立即锁定密码库并清除未保存的草稿。恢复后需要重新解锁。" : "Windows lock or sleep locks the vault and clears unsaved drafts. Unlock again after resuming."}</p>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="button" className="secondary" onClick={onExit}>{zh ? "退出 Vault Unified" : "Quit Vault Unified"}</button>
      </section>}

      {desktop && <HelloSettings />}
      <section className="settings-section" aria-labelledby="about-heading">
        <h3 id="about-heading" className="section-title">{t("settings.about")}</h3>
        <dl className="status-grid">
          <div className="status-row">
            <dt>{t("settings.product")}</dt>
            <dd>Vault Unified</dd>
          </div>
          <div className="status-row">
            <dt>{t("settings.version")}</dt>
            <dd>{packageMetadata.version}</dd>
          </div>
          <div className="status-row">
            <dt>{t("settings.platform")}</dt>
            <dd>Windows</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
