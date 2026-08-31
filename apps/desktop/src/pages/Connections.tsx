import { useState } from "react";
import ConnectionTools from "../components/ConnectionTools";
import IntegrationManager from "../components/IntegrationManager";
import { useI18n } from "../i18n";
import SyncPanel from "./SyncPanel";

interface Props {
  conflictCount: number;
  onOpenConflicts: () => void;
  onSyncDone: () => void;
}

export default function Connections({ conflictCount, onOpenConflicts, onSyncDone }: Props) {
  const { locale } = useI18n();
  const zh = locale === "zh";
  const [showSyncDetails, setShowSyncDetails] = useState(false);

  return (
    <div className="card">
      <h2>{zh ? "连接" : "Connections"}</h2>
      <p className="field-hint">
        {zh
          ? "外部密码服务和浏览器扩展都是可选的。密码可以只保存在这台设备。"
          : "External password services and the browser extension are optional. Passwords can stay only on this device."}
      </p>

      {conflictCount > 0 && (
        <div className="context-notice context-notice-warning" role="status">
          <span>
            {zh
              ? `有 ${conflictCount} 个账号在这台设备和某个已连接服务中都发生了修改，需要处理。`
              : `${conflictCount} account${conflictCount === 1 ? "" : "s"} changed both on this device and in a connected service.`}
          </span>
          <button type="button" className="secondary" onClick={onOpenConflicts}>
            {zh ? "处理冲突" : "Review changes"}
          </button>
        </div>
      )}

      <IntegrationManager />
      <ConnectionTools />

      <section className="settings-section" aria-labelledby="sync-details-heading">
        <h3 id="sync-details-heading" className="section-title">
          {zh ? "同步状态" : "Sync status"}
        </h3>
        <p className="field-hint">
          {zh
            ? "正常同步会在后台进行。只有待同步、失败或冲突时才需要查看详情。"
            : "Normal sync runs in the background. Open details only for pending changes, failures, or conflicts."}
        </p>
        <button type="button" className="secondary" onClick={() => setShowSyncDetails((value) => !value)} aria-expanded={showSyncDetails}>
          {showSyncDetails ? (zh ? "隐藏同步详情" : "Hide sync details") : (zh ? "查看同步详情" : "Review sync details")}
        </button>
        {showSyncDetails && (
          <div className="nested-panel">
            <SyncPanel onOpenConflicts={onOpenConflicts} onSyncDone={onSyncDone} />
          </div>
        )}
      </section>
    </div>
  );
}
