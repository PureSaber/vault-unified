import { useEffect, useRef, useState } from "react";
import { api, type TotpCode } from "../api/client";
import { useI18n } from "../i18n";
import PasswordField from "./PasswordField";
import { useToast } from "./Toast";

interface Props { value: string; onChange: (value: string) => void; savedValue?: string; entryId?: string }

export default function TotpEditor({ value, onChange, savedValue, entryId }: Props) {
  const { locale } = useI18n();
  const zh = locale === "zh";
  const { showToast } = useToast();
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState<(TotpCode & { deadline: number }) | null>(null);
  const [clock, setClock] = useState(performance.now());
  const [error, setError] = useState("");
  const [reading, setReading] = useState(false);
  const sequence = useRef(0);
  const picker = useRef<HTMLInputElement>(null);
  useEffect(() => () => { ++sequence.current; }, []);
  useEffect(() => {
    setResult(null);
    if (!open || !value) return;
    let cancelled = false;
    let refreshTimer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      const started = performance.now();
      try {
        const code = await api.previewTotp(value);
        if (cancelled) return;
        if (!code.valid) { setError(zh ? "无法生成验证码，请检查密钥或 otpauth 地址。" : "Cannot generate a code. Check the key or otpauth address."); setResult(null); return; }
        const remaining = Math.max(0, code.remaining_seconds * 1000 - (performance.now() - started));
        setResult({ ...code, deadline: performance.now() + remaining }); setError("");
        refreshTimer = setTimeout(() => void refresh(), Math.max(100, remaining + 40));
      } catch { if (!cancelled) { setResult(null); setError(zh ? "无法读取验证码，请重试。" : "Could not read the code. Try again."); } }
    };
    refreshTimer = setTimeout(() => void refresh(), 250);
    const tick = window.setInterval(() => setClock(performance.now()), 200);
    const hide = () => setOpen(false);
    const expiry = window.setTimeout(hide, 30_000);
    window.addEventListener("blur", hide); document.addEventListener("visibilitychange", hide);
    return () => { cancelled = true; clearTimeout(refreshTimer); clearTimeout(expiry); clearInterval(tick); window.removeEventListener("blur", hide); document.removeEventListener("visibilitychange", hide); };
  }, [open, value, zh]);
  async function readQr(file: File | undefined) {
    if (!file) return;
    const stamp = ++sequence.current;
    setReading(true); setOpen(false); setError("");
    let objectUrl = "";
    try {
      if (file.size > 4 * 1024 * 1024 || !["image/png", "image/jpeg", "image/webp"].includes(file.type)) throw new Error();
      objectUrl = URL.createObjectURL(file);
      const picture = new Image();
      picture.src = objectUrl;
      await picture.decode();
      if (!picture.width || !picture.height || picture.width * picture.height > 16_777_216) throw new Error();
      const scale = Math.min(1, 2048 / Math.max(picture.width, picture.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(picture.width * scale); canvas.height = Math.round(picture.height * scale);
      const context = canvas.getContext("2d", { willReadFrequently: true });
      if (!context) throw new Error();
      context.drawImage(picture, 0, 0, canvas.width, canvas.height);
      const { default: jsQR } = await import("jsqr");
      const decoded = jsQR(context.getImageData(0, 0, canvas.width, canvas.height).data, canvas.width, canvas.height);
      canvas.width = 0; canvas.height = 0;
      if (!decoded || !decoded.data.toLowerCase().startsWith("otpauth://totp/") || decoded.data.length > 1024) throw new Error();
      const checked = await api.previewTotp(decoded.data);
      if (!checked.valid) throw new Error();
      if (stamp === sequence.current) { onChange(decoded.data); showToast(zh ? "二维码已载入草稿，保存后生效" : "QR code loaded into the draft; save to keep it"); }
    } catch { if (stamp === sequence.current) setError(zh ? "未识别到有效的 TOTP 二维码。请选择 PNG、JPEG 或 WebP 图片，最大 4 MiB。" : "No valid TOTP QR code found. Choose a PNG, JPEG or WebP image up to 4 MiB."); }
    finally { if (objectUrl) URL.revokeObjectURL(objectUrl); if (stamp === sequence.current) setReading(false); }
  }
  async function copyCode() {
    if (!entryId || savedValue !== value) return;
    try { const copied = await api.copyTotp(entryId); showToast(zh ? `验证码已复制，${copied.clears_in_seconds} 秒后清除剪贴板` : `Code copied; clipboard clears in ${copied.clears_in_seconds} seconds`); }
    catch { showToast(zh ? "复制失败，请重试" : "Could not copy. Try again.", "error"); }
  }
  const remaining = result ? Math.max(0, Math.ceil((result.deadline - clock) / 1000)) : 0;
  return <section className="settings-section" aria-labelledby="entry-totp-heading">
    <h3 id="entry-totp-heading" className="section-title">{zh ? "动态验证码" : "Verification codes"}</h3>
    <PasswordField id="entry-totp" label={zh ? "验证器密钥（TOTP 密钥）" : "Authenticator key (TOTP key)"} value={value} onChange={text => { ++sequence.current; setReading(false); onChange(text); }} hint={zh ? "输入 Base32 密钥或标准 otpauth 地址，也可以从本机二维码图片录入。" : "Enter a Base32 key or standard otpauth address, or choose a local QR image."} />
    <div className="field"><input id="totp-qr" ref={picker} hidden type="file" aria-label={zh ? "选择验证码二维码图片" : "Choose authenticator QR image"} accept="image/png,image/jpeg,image/webp" disabled={reading} onChange={event => { void readQr(event.target.files?.[0]); event.target.value = ""; }} /><button type="button" className="secondary" disabled={reading} onClick={() => picker.current?.click()}>{reading ? (zh ? "正在识别…" : "Reading image…") : (zh ? "从二维码图片录入" : "Read QR image")}</button></div>
    {error && <p role="alert" className="error">{error}</p>}
    <div className="button-row">
      <button type="button" className="secondary" disabled={!value || reading} onClick={() => { setError(""); setOpen(!open); }}>{open ? (zh ? "隐藏验证码" : "Hide verification code") : (zh ? "显示验证码" : "Show verification code")}</button>
      <button type="button" className="secondary" disabled={!value || !entryId || savedValue !== value || reading} onClick={() => void copyCode()}>{zh ? "复制验证码" : "Copy verification code"}</button>
    </div>
    {open && result && <div className="totp-current"><output aria-label={zh ? "当前验证码" : "Current verification code"}>{remaining > 0 ? result.code : "—"}</output><span role="timer">{zh ? `${remaining} 秒后更新` : `Updates in ${remaining} seconds`}</span></div>}
    {value && savedValue !== value && <p className="field-hint">{zh ? "保存后可复制或在浏览器填充验证码。" : "Save before copying or filling codes in the browser."}</p>}
  </section>;
}
