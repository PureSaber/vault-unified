import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { useI18n } from "../i18n";

/** Runs only while the unlocked application is mounted, including in the tray. */
export default function PersonalSyncRunner({ paused, onOpen }: { paused: boolean; onOpen: () => void }) {
  const { locale } = useI18n(); const zh = locale === "zh";
  const pausedRef = useRef(paused); pausedRef.current = paused;
  const [failed, setFailed] = useState(false);
  const [conflicts, setConflicts] = useState(0);
  useEffect(() => {
    let disposed = false;
    let timer: number | undefined;
    const controller = new AbortController();
    async function run() {
      try {
        if (!pausedRef.current) {
          const result = await api.runPersonalSync(true, controller.signal);
          if (disposed) return;
          setFailed(false); setConflicts(result.conflicts || 0);
          if (!result.skipped && !result.busy) window.dispatchEvent(new Event("vault-personal-sync-updated"));
          if (result.changed) window.dispatchEvent(new Event("vault-entries-changed"));
        }
      } catch { if (!disposed) setFailed(true); }
      finally { if (!disposed) timer = window.setTimeout(() => void run(), 60_000); }
    }
    void run();
    return () => { disposed = true; controller.abort(); window.clearTimeout(timer); };
  }, []);
  if (!failed && !conflicts) return null;
  return <div className="context-notice context-notice-warning" role="status">
    <span>{conflicts ? (zh ? `${conflicts} 处多电脑修改冲突需要选择。` : `${conflicts} computer sync conflicts need your choice.`) : (zh ? "多电脑同步暂未完成，本地修改已保留。" : "Computer sync could not finish. Local changes were retained.")}</span>
    <button className="secondary" onClick={onOpen}>{zh ? "查看多电脑同步" : "Review computer sync"}</button>
  </div>;
}
