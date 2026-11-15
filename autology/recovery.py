"""Backup and restore of a whole platform data directory (GAP-033; R2 reliability sprint, increment C).

    python -m autology platform-backup  PLATFORM.json BACKUP_DIR [--include-secrets]
    python -m autology platform-verify  BACKUP_DIR
    python -m autology platform-restore BACKUP_DIR NEW_DATA_DIR

**What a platform keeps.** Everything is under its data directory: one SQLite store per use case
(``<workspace>/<use case>/autology.db``: records, runs, reviews, audit chains, the external-calls journal), the
use case's published model if it has one (``ontology.json``), its reporting database, and the platform's own
registries: tenancy (which tenant owns which workspace), administration (members, grants, token events), releases,
lifecycle stages, credentials (token lifetimes and revocations), and the access log. A workspace's ``secrets.json``
(a Claude key saved from the Console) is a secret: it is left out unless ``--include-secrets`` is given.

**Not in a backup, and needed to use one:** the configuration files (``platform.json``, each use case's
configuration, ontology, tools), the environment (members' tokens given by ``token_env``, integration
credentials) and the audit key (``AUTOLOGY_AUDIT_KEY``). Keep the key with the recovery instructions, never with
the backups: with the backup and the key together, records could be rewritten undetected.

**Consistency.** A live SQLite database is a main file plus a write-ahead log; copying the main file alone loses
whatever is still in the log, and copying both while they change can tear. So every database is copied with
SQLite's online backup, which reads one committed snapshot. Across databases there is no common transaction, so
the **order** matters: use-case stores (and their model) first, then the registries, then the access log. The
registries are therefore never older than the data they govern: every run in a restored store has its release,
stage, grant and token records. The other way round could restore a run without its governance, which is refused
by design (the use case would count as draft). A change made during the backup may be in the registries and not in
a store; the restored platform then treats that use case as drifted (nothing runs) until a person re-activates.

**A backup is complete or absent.** It is written to a sibling folder and renamed into place after every file was
copied, checked (SQLite integrity, every chain and every run's audit chain with the audit key) and hashed into
``MANIFEST.json``, which is itself signed with a key derived from the audit key. The writer lease of each store
is cleared in the copy (nobody holds a copy).

**A restore never overwrites.** It checks the manifest's signature and every file's hash, copies into a new
folder beside the target, verifies everything again as a platform would, and only then renames it to the target,
which must not exist (or be empty). The source backup is only read. To replace a live data directory: stop the
platform, move the old directory aside, restore, start. Restoring into another directory while the platform runs
is safe and is how a restore is rehearsed.

Limits: SQLite stores only (a PostgreSQL store is backed up with PostgreSQL's tools); the backup is as private as
the data (0700/0600 permissions here; encryption at rest and off-site copies are the operator's); retention is
the operator's schedule.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import __version__
from .audit import audit_key, workspace_key

FORMAT = 1
MANIFEST = "MANIFEST.json"
REGISTRIES = ("tenancy.db", "admin.db", "releases.db", "lifecycle.db", "credentials.db")  # copied after the stores
ACCESS_LOG = "platform.db"
STORE, MODEL, REPORTING, SECRETS = "autology.db", "ontology.json", "reporting.db", "secrets.json"


class RecoveryError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest_mac(body: Dict[str, Any], key: Optional[bytes]) -> str:
    data = json.dumps(["autology-backup-manifest", body], sort_keys=True, separators=(",", ":")).encode()
    signing = workspace_key(key, "platform:backup")
    return hmac.new(signing, data, hashlib.sha256).hexdigest() if signing else hashlib.sha256(data).hexdigest()


def data_dir_of(config_path: str) -> Path:
    """The data directory a ``platform.json`` names."""
    p = Path(config_path).resolve()
    try:
        spec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecoveryError(f"cannot read the platform configuration {p}: {exc}") from None
    if not isinstance(spec, dict) or "workspaces" not in spec:
        raise RecoveryError(f"{p} is not a platform configuration (no workspaces)")
    return (p.parent / spec.get("data_dir", "data")).resolve()


def inventory(data_dir: Path, include_secrets: bool = False) -> Tuple[List[Dict[str, str]], List[str]]:
    """What to copy, in order, and what is left out. Each item: ``path`` (relative), ``kind``, ``workspace``,
    ``use_case``."""
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise RecoveryError(f"no data directory {data_dir}")
    items: List[Dict[str, str]] = []
    skipped: List[str] = []
    for ws in sorted(p for p in data_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
        for uc in sorted(p for p in ws.iterdir() if p.is_dir() and not p.name.startswith(".")):
            for name, kind in ((STORE, "store"), (MODEL, "model"), (REPORTING, "reporting")):
                if (uc / name).is_file():
                    items.append({"path": f"{ws.name}/{uc.name}/{name}", "kind": kind, "workspace": ws.name,
                                  "use_case": uc.name})
        if (ws / SECRETS).is_file():
            if include_secrets:
                items.append({"path": f"{ws.name}/{SECRETS}", "kind": "secrets", "workspace": ws.name, "use_case": ""})
            else:
                skipped.append(f"{ws.name}/{SECRETS}")
    for name in REGISTRIES:
        if (data_dir / name).is_file():
            items.append({"path": name, "kind": "registry", "workspace": "", "use_case": ""})
    if (data_dir / ACCESS_LOG).is_file():
        items.append({"path": ACCESS_LOG, "kind": "access_log", "workspace": "", "use_case": ""})
    return items, skipped


def _read_only(path: Path) -> sqlite3.Connection:
    from urllib.parse import quote

    return sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True, timeout=30)


def _copy_database(source: Path, target: Path) -> None:
    """One committed snapshot of a live SQLite database, as a single self-contained file."""
    src = _read_only(source)
    try:
        dest = sqlite3.connect(str(target))
        try:
            src.backup(dest)
            dest.execute("PRAGMA journal_mode=DELETE")
            tables = {r[0] for r in dest.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "writer_lease" in tables:  # nobody holds a copy: a platform can open it at once
                dest.execute("DELETE FROM writer_lease")
                dest.commit()
        finally:
            dest.close()
    finally:
        src.close()


def _single_file(path: Path) -> None:
    """Back to one file with no sidecar after a verification opened it."""
    db = sqlite3.connect(str(path))
    try:
        db.execute("PRAGMA journal_mode=DELETE")
    finally:
        db.close()
    for suffix in ("-wal", "-shm"):
        side = Path(str(path) + suffix)
        if side.exists():
            side.unlink()


def _pairs(db_path: Path, table: str) -> List[Tuple[str, str]]:
    db = _read_only(db_path)
    try:
        columns = "workspace, use_case" if table != "admin_events" else "workspace, ''"
        return [(r[0], r[1]) for r in db.execute(f"SELECT DISTINCT {columns} FROM {table} ORDER BY 1, 2")]
    finally:
        db.close()


def deep_verify(folder: Path, key: Optional[bytes] = None) -> Tuple[Dict[str, Any], List[str]]:
    """Check a copied data directory the way a platform would trust it: SQLite integrity of every database, every
    registry's chain, and every run's audit chain in every store, with the keys derived from ``key``. Returns
    ``(counts, problems)``. The databases are opened (and returned to single files afterwards)."""
    from .administration import AdminLog
    from .credentials import CredentialError, CredentialRegistry
    from .lifecycle import Lifecycle
    from .releases import ReleaseRegistry
    from .store import Store
    from .tenancy import Tenancy, TenancyError

    folder = Path(folder)
    problems: List[str] = []
    counts: Dict[str, Any] = {"stores": 0, "runs": 0, "objects": 0, "workspaces": 0, "admin_events": 0,
                              "releases": 0, "stage_events": 0, "tenancy_assignments": 0, "credentials": 0}
    databases = sorted(p for p in folder.rglob("*.db"))
    for db_path in databases:
        try:
            db = _read_only(db_path)
            try:
                result = db.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                db.close()
            if result != "ok":
                problems.append(f"{db_path.relative_to(folder)}: SQLite integrity check failed ({result})")
        except sqlite3.DatabaseError as exc:
            problems.append(f"{db_path.relative_to(folder)}: not a readable SQLite database ({exc})")
    if problems:
        return counts, problems

    def key_for(ws: str) -> Optional[bytes]:
        return workspace_key(key, ws)

    try:
        if (folder / "tenancy.db").is_file():
            tenancy = Tenancy(folder / "tenancy.db", workspace_key(key, "platform:tenancy"))
            try:
                history, problem = tenancy.history()
                counts["tenancy_assignments"] = len(history)
                if problem:
                    problems.append(f"tenancy.db: {problem}")
            finally:
                tenancy.close()
        if (folder / "admin.db").is_file():
            workspaces = [ws for ws, _ in _pairs(folder / "admin.db", "admin_events")]
            admin = AdminLog(folder / "admin.db", key_for)
            try:
                for ws in workspaces:
                    events, problem = admin.events(ws)
                    counts["admin_events"] += len(events)
                    if problem:
                        problems.append(f"admin.db ({ws}): {problem}")
            finally:
                admin.close()
        if (folder / "releases.db").is_file():
            pairs = _pairs(folder / "releases.db", "release_events")
            releases = ReleaseRegistry(folder / "releases.db", key_for)
            try:
                for ws, uc in pairs:
                    state = releases.state(ws, uc)
                    counts["releases"] += len(state["items"])
                    if state["integrity_problem"]:
                        problems.append(f"releases.db ({ws}/{uc}): {state['integrity_problem']}")
            finally:
                releases.close()
        if (folder / "lifecycle.db").is_file():
            pairs = _pairs(folder / "lifecycle.db", "stage_events")
            lifecycle = Lifecycle(folder / "lifecycle.db", key_for)
            try:
                for ws, uc in pairs:
                    events, problem = lifecycle.history(ws, uc)
                    counts["stage_events"] += len(events)
                    if problem:
                        problems.append(f"lifecycle.db ({ws}/{uc}): {problem}")
            finally:
                lifecycle.close()
        if (folder / "credentials.db").is_file():
            try:
                registry = CredentialRegistry(folder / "credentials.db", workspace_key(key, "platform:credentials"))
                counts["credentials"] = len(registry.events())
                registry.close()
            except CredentialError as exc:
                problems.append(f"credentials.db: {exc}")
        seen = set()
        for store_path in sorted(folder.glob(f"*/*/{STORE}")):
            ws = store_path.parent.parent.name
            seen.add(ws)
            store = Store(store_path, audit_key=key_for(ws))
            try:
                runs = [r["run_id"] for r in store.list_runs(limit=10 ** 9)]
                bad = [r for r in runs if not store.verify_audit(r)]
                counts["stores"] += 1
                counts["runs"] += len(runs)
                counts["objects"] += store.count_instances()
                if bad:
                    problems.append(f"{store_path.relative_to(folder)}: audit chains that do not verify: "
                                    + ", ".join(bad[:10]))
            finally:
                store.close()
        counts["workspaces"] = len(seen)
        for model in sorted(folder.glob(f"*/*/{MODEL}")):
            try:
                if "entities" not in json.loads(model.read_text(encoding="utf-8")):
                    problems.append(f"{model.relative_to(folder)}: not an ontology document")
            except (OSError, ValueError) as exc:
                problems.append(f"{model.relative_to(folder)}: unreadable ({exc})")
    except (sqlite3.DatabaseError, TenancyError, ValueError) as exc:
        problems.append(f"verification stopped: {type(exc).__name__}: {exc}")
    finally:
        for db_path in databases:
            try:
                _single_file(db_path)
            except sqlite3.DatabaseError:
                pass
    return counts, problems


def _private(folder: Path) -> None:
    for path in [folder] + list(folder.rglob("*")):
        try:
            os.chmod(path, 0o700 if path.is_dir() else 0o600)
        except OSError:  # a filesystem without POSIX permissions: the operator protects the folder
            pass


def backup(data_dir: Path, target: Path, key: Optional[bytes] = None, include_secrets: bool = False,
           on_file: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Write a verified backup of ``data_dir`` to the new folder ``target``; the platform may be running.
    ``on_file`` is called before each file is copied (tests use it to change data, or to fail, mid-backup)."""
    started = time.monotonic()
    data_dir, target = Path(data_dir).resolve(), Path(target).resolve()
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise RecoveryError(f"{target} exists and is not empty: a backup is written to a new folder")
    if target == data_dir or data_dir in target.parents:
        raise RecoveryError("the backup folder must be outside the data directory")
    key = key if key is not None else audit_key()
    items, skipped = inventory(data_dir, include_secrets)
    if not any(i["kind"] in ("store", "registry") for i in items):
        raise RecoveryError(f"{data_dir} does not look like a platform data directory (no store, no registry)")
    partial = target.parent / f".{target.name}.partial-{os.getpid()}"
    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir(parents=True)
    try:
        for item in items:
            if on_file:
                on_file(item["path"])
            source, dest = data_dir / item["path"], partial / item["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            if item["path"].endswith(".db"):
                _copy_database(source, dest)
            else:
                shutil.copyfile(source, dest)
        counts, problems = deep_verify(partial, key)
        if problems:
            raise RecoveryError("the copy does not verify, no backup was kept: " + "; ".join(problems))
        files = [{**item, "bytes": (partial / item["path"]).stat().st_size, "sha256": _sha256(partial / item["path"])}
                 for item in items]
        body = {"format": FORMAT, "autology_version": __version__, "created_at": _now(), "keyed": key is not None,
                "order": "use-case stores and models, then registries, then the access log",
                "files": files, "not_included": skipped, "counts": counts,
                "needs": ["the configuration files (platform.json and what it references)",
                          "the environment: AUTOLOGY_AUDIT_KEY, members' token variables, integration credentials"]
                + (["each workspace's Claude key (secrets.json was left out): enter it again in the Console"]
                   if skipped else [])}
        (partial / MANIFEST).write_text(json.dumps({**body, "mac": _manifest_mac(body, key)}, indent=1),
                                        encoding="utf-8")
        _private(partial)
        if target.exists():
            target.rmdir()
        partial.rename(target)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return {"path": str(target), "files": len(files), "bytes": sum(f["bytes"] for f in files), "counts": counts,
            "not_included": skipped, "keyed": key is not None, "seconds": round(time.monotonic() - started, 3)}


def read_manifest(folder: Path, key: Optional[bytes] = None) -> Dict[str, Any]:
    """The manifest of a backup, after checking its signature and every file's size and hash (read-only)."""
    folder = Path(folder)
    key = key if key is not None else audit_key()
    try:
        manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecoveryError(f"{folder} is not a complete backup (no readable {MANIFEST}): {exc}") from None
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT or not isinstance(manifest.get("files"), list):
        raise RecoveryError(f"{folder}: unknown backup format")
    body = {k: v for k, v in manifest.items() if k != "mac"}
    if not hmac.compare_digest(str(manifest.get("mac", "")), _manifest_mac(body, key)):
        raise RecoveryError(
            "the backup's manifest does not verify: it was changed, or the audit key (AUTOLOGY_AUDIT_KEY) is not "
            "the one the backup was made with" + ("" if manifest.get("keyed") == (key is not None) else
                                                  " (the backup was made " + ("with" if manifest.get("keyed") else
                                                                              "without") + " an audit key)"))
    listed = set()
    for entry in manifest["files"]:
        rel = str(entry.get("path", ""))
        path = (folder / rel).resolve()
        if not rel or folder.resolve() not in path.parents:
            raise RecoveryError(f"the manifest names a file outside the backup: {rel!r}")
        listed.add(rel)
        if not path.is_file():
            raise RecoveryError(f"the backup is incomplete: {rel} is missing")
        if path.stat().st_size != entry.get("bytes") or _sha256(path) != entry.get("sha256"):
            raise RecoveryError(f"the backup is damaged: {rel} is not the file that was backed up")
    extra = sorted(str(p.relative_to(folder)) for p in folder.rglob("*")
                   if p.is_file() and str(p.relative_to(folder)) not in listed and p.name != MANIFEST)
    if extra:
        raise RecoveryError(f"the backup contains files the manifest does not list: {', '.join(extra[:5])}")
    return manifest


def verify(folder: Path, key: Optional[bytes] = None) -> Dict[str, Any]:
    """Check a backup completely without changing it: the manifest and hashes, then the deep verification on a
    temporary copy."""
    import tempfile

    key = key if key is not None else audit_key()
    manifest = read_manifest(folder, key)
    with tempfile.TemporaryDirectory(prefix="autology-verify-") as scratch:
        copy = Path(scratch) / "copy"
        _copy_files(Path(folder), copy, manifest)
        counts, problems = deep_verify(copy, key)
    if problems:
        raise RecoveryError("the backup does not verify: " + "; ".join(problems))
    return {"path": str(folder), "created_at": manifest["created_at"], "files": len(manifest["files"]),
            "counts": counts, "not_included": manifest.get("not_included", [])}


def _copy_files(source: Path, target: Path, manifest: Dict[str, Any],
                on_file: Optional[Callable[[str], None]] = None) -> None:
    for entry in manifest["files"]:
        if on_file:
            on_file(entry["path"])
        dest = target / entry["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / entry["path"], dest)


def restore(folder: Path, target: Path, key: Optional[bytes] = None,
            on_file: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Restore a backup into the new data directory ``target``. The backup is only read; the target appears only
    if everything verified; an existing, non-empty target is never touched."""
    started = time.monotonic()
    folder, target = Path(folder).resolve(), Path(target).resolve()
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise RecoveryError(f"{target} exists and is not empty: a restore never overwrites. Stop the platform, "
                            "move the old data directory aside, then restore")
    if target == folder or folder in target.parents or target in folder.parents:
        raise RecoveryError("restore into a folder outside the backup")
    key = key if key is not None else audit_key()
    manifest = read_manifest(folder, key)
    partial = target.parent / f".{target.name}.restoring-{os.getpid()}"
    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir(parents=True)
    try:
        _copy_files(folder, partial, manifest, on_file)
        counts, problems = deep_verify(partial, key)
        if problems:
            raise RecoveryError("the restored copy does not verify, nothing was put in place: " + "; ".join(problems))
        if counts != manifest.get("counts"):
            raise RecoveryError(f"the restored copy does not match the backup's record ({counts} instead of "
                                f"{manifest.get('counts')}), nothing was put in place")
        _private(partial)
        if target.exists():
            target.rmdir()
        partial.rename(target)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return {"path": str(target), "from": str(folder), "created_at": manifest["created_at"],
            "files": len(manifest["files"]), "counts": counts, "not_included": manifest.get("not_included", []),
            "needs": manifest.get("needs", []), "seconds": round(time.monotonic() - started, 3)}
