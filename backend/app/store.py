"""Account durability: mirror gamba_accounts rows to private Hostinger FTP.

gamba_accounts is USER data, not a rebuildable cache, and Render's disk is
wiped on every deploy. So every successful write also uploads {code}.json to
HOSTINGER_GAMBA_DIR (home-relative, deliberately OUTSIDE public_html, so the
blobs are never web-served), and boot restores whatever the redeploy dropped.

That FTP dir is also the migration path from pitchside: point
HOSTINGER_GAMBA_DIR at the dir pitchside's gamba_store.py writes and restore()
adopts every existing account. Empty FTP creds => inert.

push_async(code)  -> fire-and-forget upload of one account after a write
restore()         -> re-insert every FTP blob the local DB doesn't have
"""
import ftplib
import io
import json
import threading

from . import db
from .config import (
    HOSTINGER_FTP_HOST,
    HOSTINGER_FTP_PASSWORD,
    HOSTINGER_FTP_USER,
    HOSTINGER_GAMBA_DIR,
)

# one FTP session at a time
_lock = threading.Lock()

# codes whose last upload failed; every later push retries them under the lock.
# In-process only: if the process dies first, sqlite still has the row and the
# next write (or deploy-then-first-write) re-uploads it.
_pending: set[str] = set()


def _have_creds() -> bool:
    return bool(HOSTINGER_FTP_HOST and HOSTINGER_FTP_USER and HOSTINGER_FTP_PASSWORD)


def ftp_connect():
    """Explicit-TLS FTPS, falling back to plain FTP if the host won't negotiate."""
    try:
        ftp = ftplib.FTP_TLS(timeout=30)
        ftp.connect(HOSTINGER_FTP_HOST, 21)
        ftp.login(HOSTINGER_FTP_USER, HOSTINGER_FTP_PASSWORD)
        ftp.prot_p()
        return ftp
    except ftplib.all_errors:
        ftp = ftplib.FTP(timeout=30)
        ftp.connect(HOSTINGER_FTP_HOST, 21)
        ftp.login(HOSTINGER_FTP_USER, HOSTINGER_FTP_PASSWORD)
        return ftp


def _cwd_store(ftp) -> None:
    """Enter the accounts dir, creating it on first use (single home-level segment)."""
    d = HOSTINGER_GAMBA_DIR.rstrip("/") or "/"
    try:
        ftp.mkd(d)
    except ftplib.error_perm:
        pass  # already exists
    ftp.cwd(d)


def _read_row(code: str) -> dict | None:
    conn = db.connect()
    try:
        return conn.execute(
            "SELECT code, rev, state, updated_at FROM gamba_accounts WHERE code = ?",
            (code,),
        ).fetchone()
    finally:
        conn.close()


def _push(code: str) -> None:
    with _lock:
        todo = sorted({code} | _pending)
        ftp = None
        try:
            ftp = ftp_connect()
            _cwd_store(ftp)
            for c in todo:
                # re-read at upload time: rapid successive writes coalesce, and a
                # thread that lost the race simply uploads the newer rev — a stale
                # blob can never overwrite a fresher one.
                row = _read_row(c)
                if row is None:
                    _pending.discard(c)  # vanished (test DB churn) — nothing to keep
                    continue
                payload = {**row, "state": json.loads(row["state"])}
                blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                try:
                    ftp.storbinary(f"STOR {c}.json", io.BytesIO(blob.encode("utf-8")))
                    _pending.discard(c)
                except ftplib.all_errors:
                    _pending.add(c)
        except ftplib.all_errors:
            _pending.update(todo)  # connect/cwd failed — retry the lot next push
        finally:
            if ftp is not None:
                try:
                    ftp.quit()
                except ftplib.all_errors:
                    ftp.close()


def push_async(code: str) -> None:
    """Upload one account in the background; the API response never waits on FTP."""
    if not _have_creds():
        return
    threading.Thread(target=_push, args=(code,), daemon=True).start()


def restore() -> int:
    """Re-insert every archived account the local DB doesn't already have.

    INSERT OR IGNORE per row, not a table-empty gate: if an eager client PUT
    lands before restore finishes, the row it just wrote wins over the FTP copy
    (the client holds full state and its union merge re-supersets the account).
    Returns the number of accounts inserted.
    """
    if not _have_creds():
        return 0
    inserted = 0
    with _lock:
        ftp = None
        try:
            ftp = ftp_connect()
            _cwd_store(ftp)
            names = [n for n in ftp.nlst() if n.endswith(".json")]
            conn = db.connect()
            try:
                for name in names:
                    buf = io.BytesIO()
                    try:
                        ftp.retrbinary(f"RETR {name}", buf.write)
                        row = json.loads(buf.getvalue())
                    except (ftplib.all_errors, ValueError):
                        continue  # one bad blob must not sink the restore
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO gamba_accounts"
                        " (code, rev, state, updated_at) VALUES (?, ?, ?, ?)",
                        (row["code"], row["rev"],
                         json.dumps(row["state"], ensure_ascii=False,
                                    separators=(",", ":")),
                         row["updated_at"]),
                    )
                    inserted += cur.rowcount
                conn.commit()
            finally:
                conn.close()
        except ftplib.all_errors:
            pass  # FTP down at boot: serve from sqlite; blobs return on next push
        finally:
            if ftp is not None:
                try:
                    ftp.quit()
                except ftplib.all_errors:
                    ftp.close()
    return inserted
