import type { TemplateData } from "../api/client";

export function templateDisplay(data: TemplateData | undefined, zh: boolean): string {
  if (!data) return "—";
  const labels = { registered_to: zh ? "登记人" : "Registered to", expires_on: zh ? "到期日" : "Expiry date", environment: zh ? "环境" : "Environment", scopes: zh ? "权限范围" : "Scopes" };
  const lines = Object.entries(labels).flatMap(([key, label]) => {
    const value = data[key as keyof typeof labels];
    return value ? [`${label}: ${value}`] : [];
  });
  for (const [index, code] of (data.recovery_codes || []).entries()) {
    lines.push(`${zh ? "恢复码" : "Recovery code"} ${index + 1}: ${code.value} (${code.used_at ? `${zh ? "已使用" : "Used"} ${new Date(code.used_at).toLocaleString(zh ? "zh" : "en")}` : (zh ? "未使用" : "Unused")})`);
  }
  return lines.join("\n") || "—";
}
