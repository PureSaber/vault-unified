from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class UnlockRequest(BaseModel):
    password: str
    remember: bool = False


class CreateVaultRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)
    confirm_password: str = Field(min_length=1, max_length=1024)
    remember: bool = False


class RestoreVaultRequest(BaseModel):
    backup_path: str = Field(min_length=1, max_length=32768)
    password: str = Field(min_length=1, max_length=1024)
    remember: bool = False


class RestoreVaultApplyIn(BaseModel):
    preview_token: str = Field(min_length=32, max_length=512)
    password: str = Field(min_length=1, max_length=1024)
    remember: bool = False
    confirm_restore: bool = False


class RecoveryKitCreateIn(BaseModel):
    recovery_code: str = Field(min_length=32, max_length=512)
    confirm_recovery_code: str = Field(min_length=32, max_length=512)
    destination_dir: str | None = Field(default=None, max_length=32768)


class EmergencyRecoveryIn(BaseModel):
    kit_path: str = Field(min_length=1, max_length=32768)
    recovery_code: str = Field(min_length=32, max_length=512)
    new_password: str = Field(min_length=1, max_length=1024)
    confirm_new_password: str = Field(min_length=1, max_length=1024)
    confirm_recovery: bool = False


class EmergencyRecoveryPreviewIn(BaseModel):
    kit_path: str = Field(min_length=1, max_length=32768)
    recovery_code: str = Field(min_length=32, max_length=512)


class EmergencyRecoveryApplyIn(BaseModel):
    preview_token: str = Field(min_length=32, max_length=512)
    recovery_code: str = Field(min_length=32, max_length=512)
    new_password: str = Field(min_length=1, max_length=1024)
    confirm_new_password: str = Field(min_length=1, max_length=1024)
    confirm_recovery: bool = False


class BrowserFillIn(BaseModel):
    entry_id: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=1, max_length=8_192)


class UnlockResponse(BaseModel):
    token: str
    message: str = "unlocked"


class VaultInfoOut(BaseModel):
    exists: bool
    format: Literal["missing", "legacy", "v3", "unreadable"]
    path: str


class EntryOut(BaseModel):
    id: str
    title: str
    username: str = ""
    password: str = ""
    url: str = ""
    notes: str = ""
    has_password: bool = False
    has_notes: bool = False
    source: str
    tags: list[str] = Field(default_factory=list)
    sync_status: str
    linked_sources: dict[str, str] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    entry_type: Literal["login", "secure_note", "card", "identity", "ssh_key", "recovery_code"] = "login"
    custom_fields: list[dict[str, Any]] = Field(default_factory=list)
    totp_secret: str = ""
    has_totp_secret: bool = False
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    history_count: int = 0


class EntryIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    username: str = ""
    password: str = ""
    url: str = ""
    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    entry_type: Literal["login", "secure_note", "card", "identity", "ssh_key", "recovery_code"] = "login"
    custom_fields: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    totp_secret: str = Field(default="", max_length=1024)


class EntryUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    username: str | None = None
    password: str | None = None
    url: str | None = None
    notes: str | None = None
    tags: list[str] | None = None
    entry_type: Literal["login", "secure_note", "card", "identity", "ssh_key", "recovery_code"] | None = None
    custom_fields: list[dict[str, Any]] | None = Field(default=None, max_length=32)
    totp_secret: str | None = Field(default=None, max_length=1024)


class AttachmentIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=255)
    data_b64: str = Field(min_length=1, max_length=1_400_000)


class EntryTransactionIn(BaseModel):
    transaction_id: str = Field(min_length=16, max_length=128)
    entry_id: str | None = Field(default=None, min_length=1, max_length=128)
    expected_updated_at: str | None = Field(default=None, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    username: str = ""
    password: str = ""
    url: str = ""
    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    entry_type: Literal["login", "secure_note", "card", "identity", "ssh_key", "recovery_code"] = "login"
    custom_fields: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    totp_secret: str = Field(default="", max_length=1024)
    add_attachments: list[AttachmentIn] = Field(default_factory=list, max_length=10)
    remove_attachment_ids: list[str] = Field(default_factory=list, max_length=10)
    restore_history_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("remove_attachment_ids")
    @classmethod
    def attachment_removals_are_unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("attachment removals must be unique")
        return value


class IntegrationFieldOut(BaseModel):
    key: str
    label: str
    secret: bool
    required: bool
    value: str = ""
    present: bool = False
    origin: str = ""


class IntegrationOut(BaseModel):
    source: str
    label: str
    configured: bool
    cli_installed: bool = False
    fields: list[IntegrationFieldOut] = Field(default_factory=list)


class IntegrationUpdateIn(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)
    clear: list[str] = Field(default_factory=list)


class IntegrationTestOut(BaseModel):
    source: str
    configured: bool
    available: bool
    message: str


class BackupCreateIn(BaseModel):
    destination_dir: str | None = Field(default=None, max_length=32768)


class BackupPinIn(BaseModel):
    path: str = Field(min_length=1, max_length=32768)
    pinned: bool


class BackupPruneIn(BaseModel):
    apply: bool = False
    newest_count: int = Field(default=10, ge=0, le=1000)
    daily_days: int = Field(default=30, ge=0, le=3650)
    weekly_weeks: int = Field(default=12, ge=0, le=520)
    preview_token: str | None = Field(default=None, min_length=32, max_length=512)


class BackupRestoreIn(BaseModel):
    path: str = Field(min_length=1, max_length=32768)
    password: str = Field(default="", max_length=1024)
    confirm_restore: bool = False


class BackupRestorePreviewIn(BaseModel):
    path: str = Field(min_length=1, max_length=32768)
    password: str = Field(default="", max_length=1024)


class BackupRestoreApplyIn(BaseModel):
    preview_token: str = Field(min_length=32, max_length=512)
    password: str = Field(default="", max_length=1024)
    confirm_restore: bool = False


class RestorePreviewCancelIn(BaseModel):
    preview_token: str = Field(min_length=32, max_length=512)


class BackupVerifyIn(BaseModel):
    path: str | None = Field(default=None, max_length=32768)


class BackupDestinationTestIn(BaseModel):
    destination_dir: str = Field(min_length=1, max_length=32768)


class SyncPreferencesOut(BaseModel):
    primary: str
    auto_push_on_edit: bool
    auto_pull_on_sync: bool
    conflict_default: str
    proton_vault_name: str = ""
    proton_share_id: str = ""
    enabled_sources: list[str] | None = None


class SyncPreferencesIn(BaseModel):
    primary: str | None = None
    auto_push_on_edit: bool | None = None
    auto_pull_on_sync: bool | None = None
    conflict_default: Literal["primary", "manual"] | None = None
    proton_vault_name: str | None = None
    proton_share_id: str | None = None
    enabled_sources: list[str] | None = None


class SyncPreviewIn(BaseModel):
    include_pull: bool = True
    include_push: bool = True
    sources: list[str] | None = Field(default=None, max_length=16)


class SyncExecuteIn(BaseModel):
    preview_token: str = Field(min_length=32, max_length=512)


class ConflictResolveIn(BaseModel):
    choice: Literal["local", "remote", "merge"]
    merged: dict[str, Any] | None = None

    @field_validator("merged")
    @classmethod
    def merge_requires_body(cls, value: dict | None, info):
        return value


class StatusOut(BaseModel):
    components: dict[str, str]


class PersonalSettingsOut(BaseModel):
    lock_after_seconds: int
    auto_backup_enabled: bool
    auto_backup_interval_hours: int
    auto_backup_destination: str
    last_auto_backup_at: str = ""
    backup_status: dict[str, str] = Field(default_factory=dict)


class PersonalSettingsIn(BaseModel):
    lock_after_seconds: int | None = Field(default=None, ge=60, le=3600)
    auto_backup_enabled: bool | None = None
    auto_backup_interval_hours: int | None = Field(default=None, ge=1, le=720)
    auto_backup_destination: str | None = Field(default=None, max_length=32768)


class TransferImportIn(BaseModel):
    format: Literal["json", "csv"]
    # Secret-bearing content is size-checked inside the import parser so a
    # Pydantic 422 response cannot echo the plaintext as a rejected input.
    content: str = ""
    confirm_plaintext: bool = False


class TransferImportDecisionIn(BaseModel):
    preview_id: str = Field(min_length=1, max_length=64)
    action: Literal["skip", "create", "update"]
    target_entry_id: str | None = Field(default=None, min_length=1, max_length=128)


class TransferImportApplyIn(BaseModel):
    preview_token: str = Field(min_length=32, max_length=512)
    decisions: list[TransferImportDecisionIn] = Field(default_factory=list, max_length=5_000)


class TransferImportCancelIn(BaseModel):
    preview_token: str = Field(min_length=32, max_length=512)


class TransferImportUndoIn(BaseModel):
    transaction_id: str = Field(min_length=16, max_length=128)


class TransferExportIn(BaseModel):
    format: Literal["json", "csv"]
    confirm_plaintext: bool = False
