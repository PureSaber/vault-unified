import ConfirmDialog from "./ConfirmDialog";
import { useI18n } from "../i18n";

export default function DiscardChanges({ open, onConfirm, onCancel }: {
  open: boolean; onConfirm: () => void; onCancel: () => void;
}) {
  const { t } = useI18n();
  return <ConfirmDialog open={open} idPrefix="task-discard" variant="danger"
    title={t("settingsSave.discardTitle")} message={t("settingsSave.discardMessage")}
    confirmLabel={t("settingsSave.discard")} cancelLabel={t("settingsSave.keep")}
    onConfirm={onConfirm} onCancel={onCancel} />;
}
