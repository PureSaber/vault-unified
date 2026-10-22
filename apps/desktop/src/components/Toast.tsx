import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useI18n } from "../i18n";

type ToastType = "success" | "error" | "info";
interface ToastItem { id: number; message: string; type: ToastType }
interface ToastContextValue { showToast: (message: string, type?: ToastType) => void }
const ToastContext = createContext<ToastContextValue | null>(null);
let toastSeq = 0;

function Toast({ item, dismiss }: { item: ToastItem; dismiss: (id: number) => void }) {
  const { locale } = useI18n();
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const remaining = useRef(4000);
  useEffect(() => {
    if (item.type === "error" || hovered || focused) return;
    const start = performance.now();
    const timer = window.setTimeout(() => dismiss(item.id), remaining.current);
    return () => { clearTimeout(timer); remaining.current = Math.max(0, remaining.current - (performance.now() - start)); };
  }, [item.id, item.type, hovered, focused, dismiss]);
  return <div className={`toast toast-${item.type}`}
    onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
    onFocusCapture={() => setFocused(true)} onBlurCapture={event => { if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false); }}>
    <span role={item.type === "error" ? "alert" : "status"} aria-atomic="true">{item.message}</span>
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
    window.addEventListener("vault-ui-locked", clear);
    return () => window.removeEventListener("vault-ui-locked", clear);
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
