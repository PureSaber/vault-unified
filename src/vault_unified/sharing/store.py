"""SQLite ACLs and ciphertext. Each request uses one database transaction."""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .protocol import (SharingError, canonical, decode, identifier, member_id, validate_blob,
                       validate_manifest, verify, verify_request)


class ServiceError(SharingError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names.split()): raise ServiceError(400, "Invalid sharing fields")


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high: raise ServiceError(400, "Invalid sharing limit")
    return value


def secret_hash(value):
    return hashlib.sha256(decode(value, 32)).hexdigest()


def content_value(group, epoch, revision, blob):
    return {"version": 1, "group": group, "epoch": epoch, "revision": revision, "blob": blob}


class Store:
    def __init__(self, path: Path, *, clock=time.time, quota_bytes=256 * 1024 * 1024):
        self.path, self.clock, self.quota = Path(path), clock, quota_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = self.connect()
        try:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1}: raise SharingError("Unsupported sharing database version")
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS nonces(identity TEXT, nonce TEXT, expires INTEGER, PRIMARY KEY(identity,nonce));
                CREATE TABLE IF NOT EXISTS shares(id TEXT PRIMARY KEY, owner TEXT NOT NULL, read_hash TEXT NOT NULL,
                  blob TEXT NOT NULL, expires INTEGER NOT NULL, max_reads INTEGER NOT NULL, reads INTEGER NOT NULL DEFAULT 0,
                  revoked INTEGER NOT NULL DEFAULT 0, creation_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS families(id TEXT PRIMARY KEY, owner TEXT NOT NULL, revision INTEGER NOT NULL,
                  manifest TEXT NOT NULL, manifest_signature TEXT NOT NULL, blob TEXT NOT NULL,
                  author TEXT NOT NULL, content_revision INTEGER NOT NULL, content_signature TEXT NOT NULL, creation_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS invitations(id TEXT PRIMARY KEY, family TEXT NOT NULL, secret_hash TEXT NOT NULL,
                  role TEXT NOT NULL, expires INTEGER NOT NULL, accepted TEXT);
                CREATE TABLE IF NOT EXISTS pending(id TEXT PRIMARY KEY, family TEXT NOT NULL, identity TEXT NOT NULL,
                  public TEXT NOT NULL, role TEXT NOT NULL, expires INTEGER NOT NULL);
                PRAGMA user_version=1;
            """)
        finally: db.close()

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            now = int(self.clock())
            db.execute("DELETE FROM nonces WHERE expires < ?", (now,))
            db.execute("UPDATE shares SET blob='' WHERE expires <= ? AND blob != ''", (now,))
            db.execute("DELETE FROM shares WHERE expires < ?", (now - 30 * 86400,))
            db.execute("DELETE FROM invitations WHERE expires <= ?", (now,))
            db.execute("DELETE FROM pending WHERE expires <= ?", (now,))
            yield db, now
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally: db.close()

    def authenticate(self, db, value, path, now):
        who = verify_request(value, path, now)
        if db.execute("SELECT COUNT(*) FROM nonces").fetchone()[0] >= 100000:
            raise ServiceError(429, "Sharing service is busy")
        try: db.execute("INSERT INTO nonces VALUES (?,?,?)", (who, value["nonce"], now + 120))
        except sqlite3.IntegrityError: raise ServiceError(409, "Sharing request was already used") from None
        return who, value["payload"]

    def quota_check(self, db, additional):
        size = db.execute("SELECT COALESCE(SUM(length(blob)),0) FROM shares").fetchone()[0]
        size += db.execute("SELECT COALESCE(SUM(length(blob)+length(manifest)),0) FROM families").fetchone()[0]
        if size + additional > self.quota: raise ServiceError(507, "Sharing storage quota reached")

    def share_create(self, signed, path):
        with self.transaction() as (db, now):
            owner, payload = self.authenticate(db, signed, path, now)
            fields(payload, "id capability blob expires max_reads")
            sid = identifier(payload["id"])
            validate_blob(payload["blob"])
            cap_hash = secret_hash(payload["capability"])
            fingerprint = hashlib.sha256(canonical(payload)).hexdigest()
            existing = db.execute("SELECT * FROM shares WHERE id=?", (sid,)).fetchone()
            if existing:
                if existing["owner"] == owner and existing["revoked"] and existing["creation_hash"] == "": return self.share_info(existing)
                if existing["owner"] != owner or existing["creation_hash"] != fingerprint: raise ServiceError(409, "Share already exists")
                return self.share_info(existing)
            integer(payload["expires"], now + 60, now + 30 * 86400)
            integer(payload["max_reads"], 1, 100)
            if db.execute("SELECT COUNT(*) FROM shares").fetchone()[0] >= 10000: raise ServiceError(507, "Share limit reached")
            self.quota_check(db, len(payload["blob"]))
            db.execute("INSERT INTO shares(id,owner,read_hash,blob,expires,max_reads,creation_hash) VALUES(?,?,?,?,?,?,?)",
                       (sid, owner, cap_hash, payload["blob"], payload["expires"], payload["max_reads"], fingerprint))
            return self.share_info(db.execute("SELECT * FROM shares WHERE id=?", (sid,)).fetchone())

    @staticmethod
    def share_info(row):
        return {key: row[key] for key in ("id", "expires", "max_reads", "reads", "revoked")}

    def share_read(self, sid, payload):
        identifier(sid); fields(payload, "capability")
        capability = secret_hash(payload["capability"])
        with self.transaction() as (db, now):
            row = db.execute("SELECT * FROM shares WHERE id=?", (sid,)).fetchone()
            if (not row or not hmac.compare_digest(row["read_hash"], capability) or row["revoked"]
                    or row["expires"] <= now or row["reads"] >= row["max_reads"]):
                raise ServiceError(410, "This share is unavailable")
            blob = row["blob"]
            db.execute("UPDATE shares SET reads=reads+1, blob=CASE WHEN reads+1>=max_reads THEN '' ELSE blob END WHERE id=?", (sid,))
            return {"version": 1, "blob": blob, "expires": row["expires"], "remaining_reads": row["max_reads"] - row["reads"] - 1}

    def share_manage(self, signed, path, sid, action, *, allow_missing=False):
        identifier(sid)
        with self.transaction() as (db, now):
            who, payload = self.authenticate(db, signed, path, now); fields(payload, "")
            row = db.execute("SELECT * FROM shares WHERE id=?", (sid,)).fetchone()
            if not row and action == "revoke" and allow_missing:
                if db.execute("SELECT COUNT(*) FROM shares").fetchone()[0] >= 10000: raise ServiceError(507, "Share limit reached")
                # An authenticated publisher may cancel a delayed create before it arrives.
                db.execute("INSERT INTO shares VALUES(?,?,?,?,?,?,?,?,?)", (sid, who, "", "", now + 30 * 86400, 1, 0, 1, ""))
                row = db.execute("SELECT * FROM shares WHERE id=?", (sid,)).fetchone()
            if not row or row["owner"] != who: raise ServiceError(404, "Share not found")
            if action == "revoke": db.execute("UPDATE shares SET revoked=1,blob='' WHERE id=?", (sid,))
            return self.share_info(db.execute("SELECT * FROM shares WHERE id=?", (sid,)).fetchone())

    def family_create(self, signed, path):
        with self.transaction() as (db, now):
            who, payload = self.authenticate(db, signed, path, now)
            fields(payload, "id manifest manifest_signature blob content_signature")
            gid = identifier(payload["id"]); owner = signed["identity"]
            manifest = validate_manifest(payload["manifest"], owner, payload["manifest_signature"], gid)
            if manifest["epoch"] != 1 or set(manifest["members"]) != {who}: raise ServiceError(400, "Create an owner-only family first")
            blob = validate_blob(payload["blob"])
            verify(owner, content_value(gid, 1, 1, blob), payload["content_signature"])
            old = db.execute("SELECT * FROM families WHERE id=?", (gid,)).fetchone()
            fingerprint = hashlib.sha256(canonical(payload)).hexdigest()
            if old:
                if old["owner"] != owner or old["creation_hash"] != fingerprint: raise ServiceError(409, "Family already exists")
                return {"id": gid, "revision": old["revision"]}
            if db.execute("SELECT COUNT(*) FROM families").fetchone()[0] >= 1000: raise ServiceError(507, "Family limit reached")
            self.quota_check(db, len(blob) + len(canonical(manifest)))
            db.execute("INSERT INTO families VALUES(?,?,?,?,?,?,?,?,?,?)", (gid, owner, 1, canonical(manifest).decode(), payload["manifest_signature"], blob, owner, 1, payload["content_signature"], fingerprint))
            return {"id": gid, "revision": 1}

    def family(self, db, gid, who, *, owner=False):
        identifier(gid)
        row = db.execute("SELECT * FROM families WHERE id=?", (gid,)).fetchone()
        if not row: raise ServiceError(404, "Shared vault not found")
        manifest = json.loads(row["manifest"])
        member = manifest["members"].get(who)
        if not member or (owner and member["role"] != "owner"): raise ServiceError(403, "Shared vault permission denied")
        return row, manifest, member

    def family_operation(self, signed, path, gid, action):
        identifier(gid)
        with self.transaction() as (db, now):
            who, payload = self.authenticate(db, signed, path, now)
            if action == "accept": return self.accept(db, now, gid, who, signed["identity"], payload)
            if action == "status":
                fields(payload, "")
                pending = db.execute("SELECT id FROM pending WHERE family=? AND identity=?", (gid, who)).fetchone()
                if pending: return {"pending": True}
            row, manifest, member = self.family(db, gid, who, owner=action in {"invite", "pending", "approve", "remove", "revoke-invite"})
            if action in {"read", "status"}:
                fields(payload, "")
                if action == "status": return {"pending": False, "revision": row["revision"]}
                return {"id": gid, "owner": row["owner"], "revision": row["revision"], "manifest": manifest,
                        "manifest_signature": row["manifest_signature"], "blob": row["blob"], "author": row["author"],
                        "content_revision": row["content_revision"], "content_signature": row["content_signature"]}
            if action == "write":
                fields(payload, "revision epoch blob content_signature")
                if member["role"] == "reader": raise ServiceError(403, "This member is read-only")
                self.revision(row, payload)
                if payload["epoch"] != manifest["epoch"]: raise ServiceError(409, "Shared vault key changed; refresh first")
                self.write_content(db, row, payload, signed["identity"], manifest["epoch"])
                return {"revision": row["revision"] + 1}
            if action == "invite":
                fields(payload, "id secret role expires")
                iid = identifier(payload["id"]); digest = secret_hash(payload["secret"])
                integer(payload["expires"], now + 60, now + 7 * 86400)
                if payload["role"] not in {"editor", "reader"}: raise ServiceError(400, "Choose editor or reader")
                old = db.execute("SELECT * FROM invitations WHERE id=?", (iid,)).fetchone()
                if old:
                    if old["family"] != gid or old["secret_hash"] != digest: raise ServiceError(409, "Invitation already exists")
                else:
                    if db.execute("SELECT COUNT(*) FROM invitations WHERE family=?", (gid,)).fetchone()[0] >= 32: raise ServiceError(400, "Invitation limit reached")
                    db.execute("INSERT INTO invitations VALUES(?,?,?,?,?,NULL)", (iid, gid, digest, payload["role"], payload["expires"]))
                return {"id": iid, "expires": payload["expires"]}
            if action == "pending":
                fields(payload, "")
                return {"requests": [{"id": r["id"], "identity": r["identity"], "public": json.loads(r["public"]), "role": r["role"], "expires": r["expires"]}
                                     for r in db.execute("SELECT * FROM pending WHERE family=?", (gid,))],
                        "invitations": [{"id": r["id"], "role": r["role"], "expires": r["expires"], "accepted": bool(r["accepted"])} for r in db.execute("SELECT * FROM invitations WHERE family=?", (gid,))]}
            if action == "revoke-invite":
                fields(payload, "id"); identifier(payload["id"])
                db.execute("DELETE FROM pending WHERE id=? AND family=?", (payload["id"], gid))
                db.execute("DELETE FROM invitations WHERE id=? AND family=?", (payload["id"], gid))
                return {"revoked": True}
            if action in {"approve", "remove"}:
                return self.membership(db, now, row, manifest, payload, action)
            raise ServiceError(404, "Unknown shared vault action")

    @staticmethod
    def revision(row, payload):
        if type(payload["revision"]) is not int or payload["revision"] != row["revision"]:
            raise ServiceError(409, "Shared vault changed; refresh and review before retrying")

    def write_content(self, db, row, payload, author, epoch):
        blob = validate_blob(payload["blob"])
        next_revision = row["revision"] + 1
        verify(author, content_value(row["id"], epoch, next_revision, blob), payload["content_signature"])
        self.quota_check(db, len(blob) - len(row["blob"]))
        db.execute("UPDATE families SET revision=?,blob=?,author=?,content_revision=?,content_signature=? WHERE id=?",
                   (next_revision, blob, author, next_revision, payload["content_signature"], row["id"]))

    def accept(self, db, now, gid, who, signing, payload):
        fields(payload, "id secret encryption_key"); identifier(payload["id"]); decode(payload["encryption_key"], 32)
        invite = db.execute("SELECT * FROM invitations WHERE id=? AND family=?", (payload["id"], gid)).fetchone()
        if not invite or not hmac.compare_digest(invite["secret_hash"], secret_hash(payload["secret"])):
            raise ServiceError(410, "Invitation is unavailable")
        if invite["accepted"] and invite["accepted"] != who: raise ServiceError(410, "Invitation was already used")
        public = canonical({"signing_key": signing, "encryption_key": payload["encryption_key"]}).decode()
        old = db.execute("SELECT * FROM pending WHERE id=?", (payload["id"],)).fetchone()
        if old and old["public"] != public: raise ServiceError(409, "Invitation identity changed")
        family = db.execute("SELECT * FROM families WHERE id=?", (gid,)).fetchone()
        if not family: raise ServiceError(404, "Shared vault not found")
        if who in json.loads(family["manifest"])["members"]: return {"pending": False, "owner": family["owner"]}
        db.execute("UPDATE invitations SET accepted=? WHERE id=?", (who, payload["id"]))
        db.execute("INSERT OR IGNORE INTO pending VALUES(?,?,?,?,?,?)", (payload["id"], gid, who, public, invite["role"], invite["expires"]))
        return {"pending": True, "owner": family["owner"]}

    def membership(self, db, now, row, old, payload, action):
        fields(payload, "revision manifest manifest_signature pending_id" if action == "approve" else "revision manifest manifest_signature removed blob content_signature")
        self.revision(row, payload)
        new = validate_manifest(payload["manifest"], row["owner"], payload["manifest_signature"], row["id"])
        before, after = old["members"], new["members"]
        if action == "approve":
            pending = db.execute("SELECT * FROM pending WHERE id=? AND family=?", (identifier(payload["pending_id"]), row["id"])).fetchone()
            if not pending: raise ServiceError(410, "Join request is unavailable")
            mid = pending["identity"]
            if mid in before or set(after) != set(before) | {mid} or new["epoch"] != old["epoch"]:
                raise ServiceError(400, "Approve exactly the invited member")
            if any(after[k] != v for k, v in before.items()): raise ServiceError(400, "Existing membership changed")
            public = json.loads(pending["public"])
            if any(after[mid][k] != v for k, v in public.items()) or after[mid]["role"] != pending["role"]:
                raise ServiceError(400, "Invited identity or role changed")
            db.execute("DELETE FROM pending WHERE family=? AND identity=?", (row["id"], mid))
            db.execute("DELETE FROM invitations WHERE family=? AND accepted=?", (row["id"], mid))
            db.execute("UPDATE families SET revision=revision+1 WHERE id=?", (row["id"],))
        else:
            removed = payload["removed"]
            if removed not in before or before[removed]["role"] == "owner" or set(after) != set(before) - {removed} or new["epoch"] != old["epoch"] + 1:
                raise ServiceError(400, "Remove one member and rotate the shared vault key")
            for mid, member in after.items():
                if any(member[k] != before[mid][k] for k in ("signing_key", "encryption_key", "role")) or member["wrapped_key"] == before[mid]["wrapped_key"]:
                    raise ServiceError(400, "Rotate every remaining member key")
            if payload["blob"] == row["blob"]: raise ServiceError(400, "Re-encrypt the shared vault")
            self.write_content(db, row, payload, row["owner"], new["epoch"])
            db.execute("DELETE FROM invitations WHERE family=?", (row["id"],))
            db.execute("DELETE FROM pending WHERE family=?", (row["id"],))
        db.execute("UPDATE families SET manifest=?,manifest_signature=? WHERE id=?", (canonical(new).decode(), payload["manifest_signature"], row["id"]))
        return {"revision": row["revision"] + 1}
