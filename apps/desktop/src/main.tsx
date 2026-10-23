import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";
import "./tokens.css";
import "./refresh.css";

// Apply the saved theme before the first paint to avoid a light/dark flash;
// AppearanceProvider keeps it current afterwards.
try {
  const saved = localStorage.getItem("vault_theme");
  document.documentElement.dataset.theme = saved === "light" || saved === "dark" ? saved
    : matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
} catch { /* A theme preference is optional. */ }

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
