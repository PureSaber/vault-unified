import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

type Theme = "system" | "light" | "dark";
const Context = createContext<{ theme: Theme; setTheme: (theme: Theme) => void }>({ theme: "system", setTheme: () => {} });
export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => {
    try { const saved = localStorage.getItem("vault_theme"); if (saved === "light" || saved === "dark") return saved; } catch { /* A theme preference is optional. */ }
    return "system";
  });
  useEffect(() => {
    const system = matchMedia("(prefers-color-scheme: dark)");
    const apply = () => { document.documentElement.dataset.theme = theme === "system" ? system.matches ? "dark" : "light" : theme; };
    apply(); system.addEventListener("change", apply);
    try { localStorage.setItem("vault_theme", theme); } catch { /* Private browser preview. */ }
    return () => system.removeEventListener("change", apply);
  }, [theme]);
  return <Context.Provider value={{ theme, setTheme }}>{children}</Context.Provider>;
}
export const useAppearance = () => useContext(Context);
