import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useI18n } from "../i18n";
import { CLIPBOARD_FEEDBACK, type ClipboardFeedback } from "../api/clipboard-feedback";

type ToastType = "success" | "error" | "info";
interface ToastItem { id: number; message: string; type: ToastType; deadline?: number }
interface ToastContextValue { showToast: (message: string, type?: ToastType) => void }
const ToastContext = createContext<ToastContextValue | null>(null);
let toastSeq = 0;

function Toast({ item, dismiss }: { item: ToastItem; dismiss: (id: number) => void }) {
  const { locale, t } = useI18n();
  const [now, setNow] = useState(performance.now());
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const remaining = useRef(4000);
  useEffect(() => {
    if (item.deadline !== undefined || item.type === "error" || hovered || focused) return;
    const start = performance.now();
    const timer = window.setTimeout(() => dismiss(item.id), remaining.current);
    return () => { clearTimeout(timer); remaining.current = Math.max(0, remaining.current - (performance.now() - start)); };
  }, [item.id, item.type, item.deadline, hovered, focused, dismiss]);
  useEffect(() => {
    if (item.deadline === undefined) return;
    const tick = () => {
      const current = performance.now();
      if (current >= item.deadline!) dismiss(item.id);
      else setNow(current);
    };
    tick();
    const timer = window.setInterval(tick, 200);
    document.addEventListener("visibilitychange", tick);
    return () => { clearInterval(timer); document.removeEventListener("visibilitychange", tick); };
  }, [item.id, item.deadline, dismiss]);
  const message = item.deadline === undefined ? item.message : t("clipboard.countdown", { seconds: Math.max(0, Math.ceil((item.deadline - now) / 1000)) });
  return <div className={`toast toast-${item.type}`}
    onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
    onFocusCapture={() => setFocused(true)} onBlurCapture={event => { if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false); }}>
    <span role={item.type === "error" ? "alert" : "status"} aria-live={item.deadline === undefined ? undefined : "off"} aria-atomic="true">{message}</span>
    {item.deadline !== undefined && <span className="sr-only" role="status">{t("clipboard.copied")}</span>}
    <button type="button" className="toast-close ghost" aria-label={locale === "zh" ? "关闭提示" : "Dismiss notification"} onClick={() => dismiss(item.id)}>×</button>
  </div>;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const dismiss = useCallback((id: number) => setToasts(items => items.filter(item => item.id !== id)), []);
  const showToast = useCallback((message: string, type: ToastType = "success") => {
    setToasts(items => [...items, { id: ++toastSeq, message, type }]);
  }, []);
  useEffect(() => {
    const clear = () => setToasts([]);
    const copied = (event: Event) => {
      const { deadline } = (event as CustomEvent<ClipboardFeedback>).detail;
      setToasts(items => [...items.filter(item => item.deadline === undefined),
        ...(deadline !== undefined && deadline > performance.now() ? [{ id: ++toastSeq, message: "", type: "success" as const, deadline }] : [])]);
    };
    window.addEventListener("vault-ui-locked", clear);
    window.addEventListener(CLIPBOARD_FEEDBACK, copied);
    return () => { window.removeEventListener("vault-ui-locked", clear); window.removeEventListener(CLIPBOARD_FEEDBACK, copied); };
  }, []);
  return <ToastContext.Provider value={{ showToast }}>
    {children}
    <div className="toast-stack">{toasts.map(item => <Toast key={item.id} item={item} dismiss={dismiss} />)}</div>
  </ToastContext.Provider>;
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used within ToastProvider");
  return context;
}
