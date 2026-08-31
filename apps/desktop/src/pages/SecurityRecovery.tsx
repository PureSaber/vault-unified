import BackupCenter from "../components/BackupCenter";
import PersonalCenter from "../components/PersonalCenter";
import { useI18n } from "../i18n";

export default function SecurityRecovery() {
  const { locale } = useI18n();
  const zh = locale === "zh";

  return (
    <div className="card">
      <h2>{zh ? "安全与恢复" : "Security & recovery"}</h2>
      <div className="security-summary" role="status">
        <strong>{zh ? "保险库：已加密" : "Vault: encrypted"}</strong>
        <span>{zh ? "密码会在这台设备上加密保存。" : "Passwords are stored encrypted on this device."}</span>
      </div>
      <PersonalCenter />
      <BackupCenter />
    </div>
  );
}
