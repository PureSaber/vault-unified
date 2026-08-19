/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_API_BOOTSTRAP_SECRET?: string;
  readonly VITE_API_INSTANCE_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
