"""Account durability: mirror gamba_accounts rows to private Hostinger FTP.

gamba_accounts is USER data, not a rebuildable cache, and Render's disk is
wiped on every deploy. So every successful write also uploads {code}.json to
HOSTINGER_GAMBA_DIR (home-relative, deliberately OUTSIDE public_html, so the
blobs are never web-served), and boot restores whatever the redeploy dropped.

That FTP dir is also the migration path from pitchside: point
HOSTINGER_GAMBA_DIR at the dir pitchside's gamba_store.py writes and restore()
adopts every existing account. HOSTINGER_GAMBA_LEGACY_DIRS lets restore() ALSO
read retired dirs during a cutover (staging-window accounts merge into the
primary dir instead of being stranded). Empty FTP creds => inert.

push_async(code)  -> queue one account for upload; a background drainer
                     coalesces bursts into one FTP session
restore()         -> re-insert every FTP blob the local DB doesn't have
save_meta_blob()/load_meta_blob() -> tiny non-account state that must survive
                     the disk wipe (e.g. the btts spend ledger)
"""
import ftplib
import io
import json
import logging
import threading

from . import db
from .config import (
    HOSTINGER_FTP_HOST,
    HOSTINGER_FTP_PASSWORD,
    HOSTINGER_FTP_USER,
    HOSTINGER_GAMBA_DIR,
    HOSTINGER_GAMBA_LEGACY_DIRS,
)

log = logging.getLogger(__name__)

# one FTP session at a time
_lock = threading.Lock()

# codes whose upload hasn't succeeded yet; the drainer retries them.
# In-process only: if the process dies first, sqlite still has the row and the
# next write (or deploy-then-first-write) re-uploads it.
_pending: set[str] = set()

# one drainer at a time; push_async spawns candidates that exit if one is live
_drain_lock = threading.Lock()


def _have_creds() -> bool:
    return bool(HOSTINGER_FTP_HOST and HOSTINGER_FTP_USER and HOSTINGER_FTP_PASSWORD)


def ftp_connect():
    """Explicit-TLS FTPS, fail-closed: no plaintext fallback. The FTP password
    also controls the site's public_html, so silently downgrading to cleartext
    port 21 risks far more than a failed push (pushes stay pending and retry;
    restore retries next boot)."""
    ftp = ftplib.FTP_TLS(timeout=30)
    try:
        ftp.connect(HOSTINGER_FTP_HOST, 21)
        ftp.login(HOSTINGER_FTP_USER, HOSTINGER_FTP_PASSWORD)
        ftp.prot_p()
        return ftp
    except ftplib.all_errors:
        log.warning("FTPS connect to %s failed; refusing plaintext fallback",
                    HOSTINGER_FTP_HOST)
        ftp.close()
        raise


def _cwd_store(ftp, dirname: str | None = None) -> None:
    """Enter an accounts dir from the FTP home, creating it on first use."""
    d = (dirname or HOSTINGER_GAMBA_DIR).rstrip("/") or "/"
    try:
        ftp.cwd("/")  # dirs are home-relative; the account chroots to home
    except ftplib.error_perm:
        pass
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


def _push_pending() -> None:
    """One FTP session uploading a snapshot of _pending. Failures stay pending."""
    with _lock:
        todo = sorted(_pending)
        ftp = None
        try:
            ftp = ftp_connect()
            _cwd_store(ftp)
            for c in todo:
                # re-read at upload time: rapid successive writes coalesce, and a
                # burst that lost the race simply uploads the newer rev — a stale
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
                    pass  # stays pending; retried on the next drain
        except ftplib.all_errors:
            pass  # connect/cwd failed — everything stays pending
        finally:
            if ftp is not None:
                try:
                    ftp.quit()
                except ftplib.all_errors:
                    ftp.close()


def _drain() -> None:
    """Upload until _pending is empty or FTP stops making progress. A matchday
    burst of pushes lands in one FTP session instead of one handshake each.
    A code that lands just as the drainer exits stays pending and rides along
    with the next push — same eventual-upload contract _pending always had."""
    if not _drain_lock.acquire(blocking=False):
        return  # the live drainer's while-loop will pick the new codes up
    try:
        while _pending:
            before = set(_pending)
            _push_pending()
            if before <= _pending:
                break  # no progress (FTP down); the next push retries
    finally:
        _drain_lock.release()


def _push(code: str) -> None:
    """Synchronous push of one code (plus any pending). Kept for tests/ops."""
    _pending.add(code)
    _drain()


def push_async(code: str) -> None:
    """Queue one account for upload; the API response never waits on FTP."""
    if not _have_creds():
        return
    _pending.add(code)
    threading.Thread(target=_drain, daemon=True).start()


def _fetch_blobs(ftp, dirname: str) -> dict[str, dict]:
    """{code: blob} for every well-formed account blob in one FTP dir.
    A malformed blob is skipped — it must not sink the restore."""
    blobs = {}
    _cwd_store(ftp, dirname)
    for name in ftp.nlst():
        if not name.endswith(".json"):
            continue
        buf = io.BytesIO()
        try:
            ftp.retrbinary(f"RETR {name}", buf.write)
            row = json.loads(buf.getvalue())
            blobs[row["code"]] = {
                "code": row["code"], "rev": row["rev"],
                "state": row["state"], "updated_at": row["updated_at"],
            }
        except ftplib.all_errors:
            raise  # connection-level failure: let restore() handle it
        except Exception:
            continue  # bad JSON / wrong shape / missing keys
    return blobs


def restore() -> int:
    """Re-insert every archived account the local DB doesn't already have.

    INSERT OR IGNORE per row, not a table-empty gate: if an eager client PUT
    lands before restore finishes, the row it just wrote wins over the FTP copy
    (the client holds full state and its union merge re-supersets the account).

    All FTP reads happen BEFORE the DB writes: the insert transaction lasts
    milliseconds, so a slow FTP session can no longer hold the sqlite write
    lock against concurrent account writes.

    Legacy dirs are read first and the primary dir wins ties; an account only
    found in a legacy dir is queued for upload so it gains a primary-dir copy
    (that upload IS the staging->prod migration). Returns rows inserted.
    """
    if not _have_creds():
        return 0
    inserted = 0
    adopted_from_legacy = []
    with _lock:
        ftp = None
        try:
            ftp = ftp_connect()
            blobs: dict[str, dict] = {}
            for d in [*HOSTINGER_GAMBA_LEGACY_DIRS, HOSTINGER_GAMBA_DIR]:
                is_primary = d == HOSTINGER_GAMBA_DIR
                for code, blob in _fetch_blobs(ftp, d).items():
                    prev = blobs.get(code)
                    # ponytail: string-compare updated_at; only wrong when the
                    # same account was written to two dirs in the same second
                    if prev is None or blob["updated_at"] >= prev["updated_at"]:
                        blobs[code] = {**blob, "primary": is_primary}
        except ftplib.all_errors:
            blobs = None  # FTP down at boot: serve from sqlite
        finally:
            if ftp is not None:
                try:
                    ftp.quit()
                except ftplib.all_errors:
                    ftp.close()
        if blobs:
            conn = db.connect()
            try:
                for blob in blobs.values():
                    try:
                        cur = conn.execute(
                            "INSERT OR IGNORE INTO gamba_accounts"
                            " (code, rev, state, updated_at) VALUES (?, ?, ?, ?)",
                            (blob["code"], blob["rev"],
                             json.dumps(blob["state"], ensure_ascii=False,
                                        separators=(",", ":")),
                             blob["updated_at"]),
                        )
                        inserted += cur.rowcount
                        if cur.rowcount and not blob["primary"]:
                            adopted_from_legacy.append(blob["code"])
                    except Exception:
                        continue  # one bad blob must not sink the restore
                conn.commit()
            finally:
                conn.close()
    if adopted_from_legacy:
        _pending.update(adopted_from_legacy)
        threading.Thread(target=_drain, daemon=True).start()
    return inserted


# ---- non-account meta blobs -----------------------------------------------------
# Tiny state that must survive the disk wipe but isn't an account (e.g. which
# events already had their btts credit spent). '.meta' extension so restore()'s
# '.json' filter never mistakes one for an account blob.


def save_meta_blob(name: str, obj) -> None:
    """Fire-and-forget upload of one JSON-serializable object."""
    if not _have_creds():
        return

    def _save():
        with _lock:
            try:
                ftp = ftp_connect()
                try:
                    _cwd_store(ftp)
                    blob = json.dumps(obj, separators=(",", ":")).encode("utf-8")
                    ftp.storbinary(f"STOR {name}.meta", io.BytesIO(blob))
                finally:
                    try:
                        ftp.quit()
                    except ftplib.all_errors:
                        ftp.close()
            except ftplib.all_errors:
                pass  # best-effort; the caller re-saves on its next change

    threading.Thread(target=_save, daemon=True).start()


def load_meta_blob(name: str):
    """The stored object, or None (no creds / missing / FTP down)."""
    if not _have_creds():
        return None
    with _lock:
        try:
            ftp = ftp_connect()
            try:
                _cwd_store(ftp)
                buf = io.BytesIO()
                ftp.retrbinary(f"RETR {name}.meta", buf.write)
                return json.loads(buf.getvalue())
            finally:
                try:
                    ftp.quit()
                except ftplib.all_errors:
                    ftp.close()
        except (ftplib.all_errors, ValueError):
            return None
