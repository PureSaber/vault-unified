function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} was not generated for this isolated run`);
  return value;
}

export const testData = {
  runId: required("UI_TEST_RUN_ID"),
  masterPassword: required("UI_TEST_MASTER_PASSWORD"),
  entryPassword: required("UI_TEST_ENTRY_PASSWORD"),
  bearerToken: required("UI_TEST_BEARER_TOKEN"),
  bootstrapSecret: required("UI_TEST_BOOTSTRAP_SECRET"),
} as const;
