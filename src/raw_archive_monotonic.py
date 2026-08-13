"""Append-only helpers for source-backed raw archives.

Raw archives may advance when the source grows. A shorter or rewritten source
is diagnostic evidence, never permission to shrink or replace the archive.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import re
import time
from collections import OrderedDict
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, Iterator

try:
    import fcntl as _fcntl
except ImportError:  # Windows
    _fcntl = None

try:
    import msvcrt as _msvcrt
except ImportError:  # POSIX
    _msvcrt = None


CONTRACT = "time_library_raw_archive_monotonic.v1"
DIAGNOSTICS_CONTRACT = "time_library_raw_archive_io_diagnostics.v1"
CHUNK_SIZE = 1024 * 1024
DIVERGENCE_WITNESS_BYTES = 64
DIVERGENCE_WITNESS_CACHE_LIMIT = 512
MATCHED_PREFIX_CACHE_LIMIT = 512
PREFIX_PROOF_CONTRACT = "time_library_raw_prefix_proof.v1"
PREFIX_PROOF_SUFFIX = ".prefix-proof.json"
PREFIX_FULL_REVERIFY_SECONDS = 15 * 60
GENERATION_CONTRACT = "time_library_raw_archive_generation.v1"
GENERATION_DESCRIPTOR_SUFFIX = ".generation.json"
GENERATION_PENDING_SUFFIX = ".generation.pending.json"
GENERATION_LOCK_SUFFIX = ".generation.lock"
GENERATION_MAX_JSON_LINE_BYTES = 16 * 1024 * 1024
GENERATION_WITNESS_BYTES = 64
# Keep only hashes of a proven mismatch window; source bytes never enter the cache.
_DIVERGENCE_WITNESS_CACHE: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
_DIVERGENCE_WITNESS_LOCK = RLock()
# A hit is valid only while both files retain the exact stat snapshot that was
# verified byte-for-byte. The cache is process-local and stores no source data.
_MATCHED_PREFIX_CACHE: OrderedDict[
    tuple[str, str, int, int, int, int, int, int],
    str,
] = OrderedDict()
_MATCHED_PREFIX_LOCK = RLock()
_DIAGNOSTIC_COUNTERS = {
    "matched_prefix_cache_hit_count": 0,
    "matched_prefix_cache_miss_count": 0,
    "verified_prefix_rehash_hit_count": 0,
    "verified_prefix_rehash_miss_count": 0,
    "verified_prefix_rehash_source_bytes": 0,
    "checkpoint_prefix_hit_count": 0,
    "checkpoint_prefix_miss_count": 0,
    "checkpoint_prefix_source_bytes": 0,
    "periodic_full_reverify_count": 0,
    "prefix_proof_write_count": 0,
    "prefix_proof_write_failure_count": 0,
    "divergence_witness_hit_count": 0,
    "full_prefix_scan_count": 0,
    "full_prefix_source_bytes": 0,
    "full_prefix_archive_bytes": 0,
}
_DIAGNOSTIC_LOCK = RLock()


def _increment_diagnostics(**increments: int) -> None:
    with _DIAGNOSTIC_LOCK:
        for key, value in increments.items():
            if key in _DIAGNOSTIC_COUNTERS:
                _DIAGNOSTIC_COUNTERS[key] += max(0, int(value or 0))


def raw_archive_diagnostics_snapshot() -> dict[str, Any]:
    """Return process-local I/O counters without paths or source content."""
    with _DIAGNOSTIC_LOCK:
        counters = dict(_DIAGNOSTIC_COUNTERS)
    counters["full_prefix_total_bytes"] = (
        counters["full_prefix_source_bytes"] + counters["full_prefix_archive_bytes"]
    )
    return {"contract": DIAGNOSTICS_CONTRACT, **counters}


def _reset_raw_archive_diagnostics() -> None:
    with _DIAGNOSTIC_LOCK:
        for key in _DIAGNOSTIC_COUNTERS:
            _DIAGNOSTIC_COUNTERS[key] = 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _divergence_witness_key(source: Path, archive: Path) -> tuple[str, str]:
    return (os.path.normcase(os.path.abspath(source)), os.path.normcase(os.path.abspath(archive)))


def _stat_signature(value: os.stat_result) -> tuple[int, int, int]:
    return (
        int(value.st_ino),
        int(value.st_size),
        int(value.st_mtime_ns),
    )


def _matched_prefix_key(
    source: Path,
    archive: Path,
    source_stat: os.stat_result,
    archive_stat: os.stat_result,
) -> tuple[str, str, int, int, int, int, int, int]:
    source_inode, source_size, source_mtime_ns = _stat_signature(source_stat)
    archive_inode, archive_size, archive_mtime_ns = _stat_signature(archive_stat)
    source_key, archive_key = _divergence_witness_key(source, archive)
    return (
        source_key,
        archive_key,
        source_inode,
        source_size,
        source_mtime_ns,
        archive_inode,
        archive_size,
        archive_mtime_ns,
    )


def _forget_matched_prefix(source: Path, archive: Path) -> None:
    path_key = _divergence_witness_key(source, archive)
    with _MATCHED_PREFIX_LOCK:
        stale = [key for key in _MATCHED_PREFIX_CACHE if key[:2] == path_key]
        for key in stale:
            _MATCHED_PREFIX_CACHE.pop(key, None)


def _cached_prefix_match(
    source: Path,
    archive: Path,
    source_stat: os.stat_result,
    archive_stat: os.stat_result,
) -> bool:
    key = _matched_prefix_key(source, archive, source_stat, archive_stat)
    hit = False
    with _MATCHED_PREFIX_LOCK:
        if key in _MATCHED_PREFIX_CACHE:
            _MATCHED_PREFIX_CACHE.move_to_end(key)
            hit = True
    _increment_diagnostics(**{
        "matched_prefix_cache_hit_count" if hit else "matched_prefix_cache_miss_count": 1,
    })
    return hit


def _cached_prefix_sha256(
    source: Path,
    archive: Path,
    source_stat: os.stat_result,
    archive_stat: os.stat_result,
) -> str:
    key = _matched_prefix_key(source, archive, source_stat, archive_stat)
    with _MATCHED_PREFIX_LOCK:
        return str(_MATCHED_PREFIX_CACHE.get(key) or "")


def _hash_prefix(path: Path, length: int) -> tuple[Any | None, int]:
    hasher = hashlib.sha256()
    remaining = max(0, int(length))
    bytes_read = 0
    try:
        with path.open("rb") as handle:
            while remaining:
                chunk = handle.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    return None, bytes_read
                hasher.update(chunk)
                bytes_read += len(chunk)
                remaining -= len(chunk)
    except OSError:
        return None, bytes_read
    return hasher, bytes_read


def _cached_verified_prefix_match(
    source: Path,
    archive: Path,
    source_stat: os.stat_result,
    archive_stat: os.stat_result,
) -> tuple[bool, Any | None]:
    """Revalidate a growing source against the last proven prefix hash.

    The archive must still have the exact stat snapshot that was proven equal.
    Rehashing only the source prefix preserves rewrite detection while avoiding
    a second full read of the unchanged archive.
    """
    source_key, archive_key = _divergence_witness_key(source, archive)
    source_inode, source_size, _source_mtime_ns = _stat_signature(source_stat)
    archive_inode, archive_size, archive_mtime_ns = _stat_signature(archive_stat)
    candidate_key = None
    expected_sha256 = ""
    with _MATCHED_PREFIX_LOCK:
        for key in reversed(_MATCHED_PREFIX_CACHE):
            if key[:2] != (source_key, archive_key):
                continue
            if (
                key[2] == source_inode
                and key[3] == archive_size
                and key[5:] == (archive_inode, archive_size, archive_mtime_ns)
                and source_size >= archive_size
            ):
                candidate_key = key
                expected_sha256 = str(_MATCHED_PREFIX_CACHE.get(key) or "")
                break
    if candidate_key is None or not expected_sha256:
        return False, None

    hasher, bytes_read = _hash_prefix(source, archive_size)
    matched = bool(hasher is not None and hasher.hexdigest() == expected_sha256)
    _increment_diagnostics(
        **{
            "verified_prefix_rehash_hit_count" if matched else "verified_prefix_rehash_miss_count": 1,
            "verified_prefix_rehash_source_bytes": bytes_read,
        }
    )
    if matched:
        with _MATCHED_PREFIX_LOCK:
            if candidate_key in _MATCHED_PREFIX_CACHE:
                _MATCHED_PREFIX_CACHE.move_to_end(candidate_key)
        return True, hasher
    return False, None


def _remember_matched_prefix(
    source: Path,
    archive: Path,
    source_stat: os.stat_result,
    archive_stat: os.stat_result,
    source_sha256: str,
) -> None:
    _forget_divergence_witness(source, archive)
    key = _matched_prefix_key(source, archive, source_stat, archive_stat)
    with _MATCHED_PREFIX_LOCK:
        stale = [candidate for candidate in _MATCHED_PREFIX_CACHE if candidate[:2] == key[:2]]
        for candidate in stale:
            _MATCHED_PREFIX_CACHE.pop(candidate, None)
        _MATCHED_PREFIX_CACHE[key] = str(source_sha256 or "")
        _MATCHED_PREFIX_CACHE.move_to_end(key)
        while len(_MATCHED_PREFIX_CACHE) > MATCHED_PREFIX_CACHE_LIMIT:
            _MATCHED_PREFIX_CACHE.popitem(last=False)


def _same_stat_snapshot(path: Path, expected: os.stat_result) -> bool:
    try:
        current = path.stat()
    except OSError:
        return False
    return _stat_signature(current) == _stat_signature(expected)


def _checksum_fields(source: Path, archive: Path, *, compute_sha256: bool) -> dict[str, str]:
    if not compute_sha256:
        return {}
    return {
        "source_sha256": _sha256(source),
        "archive_sha256": _sha256(archive),
    }


def _window_sha256(path: Path, offset: int, length: int) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read(length)
    except OSError:
        return ""
    if len(data) != length:
        return ""
    return hashlib.sha256(data).hexdigest()


def _prefix_full_reverify_seconds() -> int:
    raw = os.environ.get("TIME_LIBRARY_PREFIX_FULL_REVERIFY_SECONDS")
    try:
        value = int(raw) if raw is not None else PREFIX_FULL_REVERIFY_SECONDS
    except (TypeError, ValueError):
        value = PREFIX_FULL_REVERIFY_SECONDS
    return max(60, min(value, 24 * 60 * 60))


def _prefix_proof_path(archive: Path) -> Path:
    return Path(str(archive) + PREFIX_PROOF_SUFFIX)


def _load_prefix_proof(archive: Path) -> dict[str, Any]:
    try:
        payload = json.loads(_prefix_proof_path(archive).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _seal_prefix_proof(proof: dict[str, Any]) -> dict[str, Any]:
    sealed = {key: value for key, value in proof.items() if key != "proof_sha256"}
    canonical = json.dumps(
        sealed,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    sealed["proof_sha256"] = hashlib.sha256(canonical).hexdigest()
    return sealed


def _prefix_proof_integrity_valid(proof: dict[str, Any]) -> bool:
    expected = str(proof.get("proof_sha256") or "")
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected.lower()):
        return False
    actual = _seal_prefix_proof(proof).get("proof_sha256")
    return bool(actual and hmac.compare_digest(actual, expected.lower()))


def _proof_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _write_prefix_proof(archive: Path, proof: dict[str, Any]) -> bool:
    target = _prefix_proof_path(archive)
    temp = target.with_name(f"{target.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    sealed = _seal_prefix_proof(proof)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(sealed, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        os.replace(temp, target)
        _increment_diagnostics(prefix_proof_write_count=1)
        return True
    except OSError:
        _increment_diagnostics(prefix_proof_write_failure_count=1)
        return False
    finally:
        try:
            temp.unlink()
        except OSError:
            pass


def _proof_block_hashes(path: Path, start_offset: int = 0) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    offset = max(0, int(start_offset))
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            while True:
                chunk = handle.read(CHUNK_SIZE)
                if not chunk:
                    break
                blocks.append({
                    "offset": offset,
                    "length": len(chunk),
                    "sha256": hashlib.sha256(chunk).hexdigest(),
                })
                offset += len(chunk)
    except OSError:
        return []
    return blocks


def _proof_archive_snapshot_matches(proof: dict[str, Any], archive_stat: os.stat_result) -> bool:
    return (
        proof.get("contract") == PREFIX_PROOF_CONTRACT
        and _prefix_proof_integrity_valid(proof)
        and _proof_int(proof.get("block_size")) == CHUNK_SIZE
        and _proof_int(proof.get("archive_inode")) == int(archive_stat.st_ino)
        and _proof_int(proof.get("archive_size"), -1) == int(archive_stat.st_size)
        and _proof_int(proof.get("archive_mtime_ns")) == int(archive_stat.st_mtime_ns)
        and isinstance(proof.get("blocks"), list)
    )


def _proof_blocks_cover_prefix(proof: dict[str, Any], prefix_size: int) -> bool:
    blocks = proof.get("blocks") if isinstance(proof.get("blocks"), list) else []
    expected_offset = 0
    for block in blocks:
        if not isinstance(block, dict):
            return False
        offset = _proof_int(block.get("offset"))
        length = _proof_int(block.get("length"))
        digest = str(block.get("sha256") or "").lower()
        if (
            offset != expected_offset
            or length <= 0
            or length > CHUNK_SIZE
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            return False
        expected_offset += length
    return expected_offset == int(prefix_size)


def _bounded_prefix_proof_match(
    source: Path,
    archive: Path,
    source_stat: os.stat_result,
    archive_stat: os.stat_result,
) -> tuple[bool, dict[str, Any]]:
    """Check a rotating historical block while a proven source grows.

    This is only eligible for same-inode growth inside the explicit full-scan
    window. Missing, stale, malformed, or identity-mismatched proof falls back
    to a full byte comparison in the caller.
    """
    proof = _load_prefix_proof(archive)
    archive_size = int(archive_stat.st_size)
    if (
        int(source_stat.st_size) <= archive_size
        or not _proof_archive_snapshot_matches(proof, archive_stat)
        or not _proof_blocks_cover_prefix(proof, archive_size)
        or _proof_int(proof.get("source_inode")) != int(source_stat.st_ino)
    ):
        return False, {}
    verified_at_ns = _proof_int(proof.get("last_full_verified_at_ns"))
    max_age_ns = _prefix_full_reverify_seconds() * 1_000_000_000
    proof_age_ns = time.time_ns() - verified_at_ns
    if not verified_at_ns or proof_age_ns < 0 or proof_age_ns > max_age_ns:
        _increment_diagnostics(periodic_full_reverify_count=1)
        return False, {}

    blocks = proof["blocks"]
    next_index = _proof_int(proof.get("next_block_index")) % len(blocks)
    indices = sorted({next_index, len(blocks) - 1})
    bytes_read = 0
    for index in indices:
        block = blocks[index]
        offset = _proof_int(block.get("offset"))
        length = _proof_int(block.get("length"))
        digest = _window_sha256(source, offset, length)
        bytes_read += length
        if not digest or digest != block.get("sha256"):
            _increment_diagnostics(
                checkpoint_prefix_miss_count=1,
                checkpoint_prefix_source_bytes=bytes_read,
                verified_prefix_rehash_miss_count=1,
                verified_prefix_rehash_source_bytes=bytes_read,
            )
            return False, {}
    _increment_diagnostics(
        checkpoint_prefix_hit_count=1,
        checkpoint_prefix_source_bytes=bytes_read,
    )
    proof = dict(proof)
    proof["next_block_index"] = (next_index + 1) % len(blocks)
    proof["last_bounded_verified_at_ns"] = time.time_ns()
    return True, _seal_prefix_proof(proof)


def _full_scan_proof(
    source_stat: os.stat_result,
    archive_stat: os.stat_result,
    blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "contract": PREFIX_PROOF_CONTRACT,
        "block_size": CHUNK_SIZE,
        "archive_inode": int(archive_stat.st_ino),
        "archive_size": int(archive_stat.st_size),
        "archive_mtime_ns": int(archive_stat.st_mtime_ns),
        "source_inode": int(source_stat.st_ino),
        "source_size_at_verification": int(source_stat.st_size),
        "last_full_verified_at_ns": time.time_ns(),
        "last_bounded_verified_at_ns": 0,
        "next_block_index": 0,
        "blocks": blocks,
        "rewrite_detection_window_seconds": _prefix_full_reverify_seconds(),
    }


def _refresh_prefix_proof_after_append(
    archive: Path,
    source_stat: os.stat_result,
    archive_size_before: int,
    archive_stat_before: os.stat_result | None,
    prior_proof: dict[str, Any] | None,
) -> bool:
    try:
        archive_stat = archive.stat()
    except OSError:
        return False
    proof = dict(prior_proof or {})
    prior_snapshot_valid = bool(
        archive_stat_before is not None
        and _proof_archive_snapshot_matches(proof, archive_stat_before)
    )
    old_blocks = (
        proof.get("blocks")
        if prior_snapshot_valid and isinstance(proof.get("blocks"), list)
        else []
    )
    start_index = max(0, int(archive_size_before) // CHUNK_SIZE) if old_blocks else 0
    start_offset = start_index * CHUNK_SIZE
    preserved = [dict(block) for block in old_blocks[:start_index] if isinstance(block, dict)]
    refreshed = _proof_block_hashes(archive, start_offset=start_offset)
    if int(archive_stat.st_size) and not refreshed and not preserved:
        return False
    verified_at_ns = _proof_int(proof.get("last_full_verified_at_ns"))
    if not old_blocks or not verified_at_ns:
        verified_at_ns = time.time_ns()
    final_proof = {
        "contract": PREFIX_PROOF_CONTRACT,
        "block_size": CHUNK_SIZE,
        "archive_inode": int(archive_stat.st_ino),
        "archive_size": int(archive_stat.st_size),
        "archive_mtime_ns": int(archive_stat.st_mtime_ns),
        "source_inode": int(source_stat.st_ino),
        "source_size_at_verification": int(source_stat.st_size),
        "last_full_verified_at_ns": verified_at_ns,
        "last_bounded_verified_at_ns": _proof_int(proof.get("last_bounded_verified_at_ns")),
        "next_block_index": _proof_int(proof.get("next_block_index")),
        "blocks": preserved + refreshed,
        "rewrite_detection_window_seconds": _prefix_full_reverify_seconds(),
    }
    if not _proof_blocks_cover_prefix(final_proof, int(archive_stat.st_size)):
        return False
    block_count = len(final_proof["blocks"])
    final_proof["next_block_index"] = (
        final_proof["next_block_index"] % block_count if block_count else 0
    )
    return _write_prefix_proof(archive, final_proof)


def _generation_descriptor_path(archive: Path) -> Path:
    return Path(str(archive) + GENERATION_DESCRIPTOR_SUFFIX)


def _generation_pending_path(archive: Path) -> Path:
    return Path(str(archive) + GENERATION_PENDING_SUFFIX)


@contextlib.contextmanager
def _exclusive_generation_lock(archive: Path) -> Iterator[None]:
    """Serialize generation mutations for one logical archive across processes."""
    base = _archive_base_path(archive)
    path = Path(str(base) + GENERATION_LOCK_SUFFIX)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
            os.fsync(stream.fileno())
        stream.seek(0)
        if _fcntl is not None:
            _fcntl.flock(stream.fileno(), _fcntl.LOCK_EX)
        elif _msvcrt is not None:
            _msvcrt.locking(stream.fileno(), _msvcrt.LK_LOCK, 1)
        else:  # pragma: no cover - all supported runtimes provide one API
            raise RuntimeError("generation_lock_unsupported")
        try:
            yield
        finally:
            if _fcntl is not None:
                _fcntl.flock(stream.fileno(), _fcntl.LOCK_UN)
            elif _msvcrt is not None:
                stream.seek(0)
                _msvcrt.locking(stream.fileno(), _msvcrt.LK_UNLCK, 1)


def _fsync_parent(path: Path) -> None:
    """Best-effort directory durability after an atomic rename."""
    try:
        fd = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        os.replace(temp, path)
        _fsync_parent(path)
    finally:
        try:
            temp.unlink()
        except OSError:
            pass


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _generation_descriptor_valid(payload: dict[str, Any]) -> bool:
    if payload.get("contract") != GENERATION_CONTRACT:
        return False
    if payload.get("state", "committed") != "committed":
        return False
    try:
        generation = int(payload.get("generation"))
        base_offset = int(payload.get("source_base_offset"))
        segment_size = int(payload.get("segment_size"))
    except (TypeError, ValueError):
        return False
    if generation < 1 or base_offset < 0 or segment_size < 0:
        return False
    if payload.get("source_covered_bytes") is not None:
        try:
            if int(payload.get("source_covered_bytes")) != base_offset + segment_size:
                return False
        except (TypeError, ValueError):
            return False
    prefix_sha = str(payload.get("source_prefix_sha256") or "")
    return len(prefix_sha) == 64 and all(char in "0123456789abcdef" for char in prefix_sha.lower())


def _generation_descriptor_bound_to_archive(
    payload: dict[str, Any],
    archive: Path,
    *,
    require_current_size: bool,
) -> bool:
    if not _generation_descriptor_valid(payload):
        return False
    if str(payload.get("segment_path") or "") not in {"", str(archive)}:
        return False
    if require_current_size:
        try:
            return int(payload.get("segment_size")) == int(archive.stat().st_size)
        except (OSError, TypeError, ValueError):
            return False
    return True


def _recover_pending_generation(archive: Path) -> dict[str, Any]:
    """Promote a fully written segment whose final descriptor rename was interrupted."""
    descriptor_path = _generation_descriptor_path(archive)
    committed = _load_json_object(descriptor_path)
    pending_path = _generation_pending_path(archive)
    committed_size_matches = _generation_descriptor_bound_to_archive(
        committed,
        archive,
        require_current_size=True,
    )
    if committed_size_matches:
        try:
            pending_path.unlink()
        except OSError:
            pass
        return committed
    pending = _load_json_object(pending_path)
    if pending.get("contract") != GENERATION_CONTRACT or pending.get("state") != "prepared":
        return {}
    if str(pending.get("segment_path") or "") != str(archive):
        return {}
    if pending.get("operation") == "append_generation":
        previous = pending.get("previous_descriptor")
        if not isinstance(previous, dict) or not _generation_descriptor_bound_to_archive(
            previous,
            archive,
            require_current_size=False,
        ):
            return {}
        expected_previous_sha = str(pending.get("previous_descriptor_sha256") or "")
        actual_previous_sha = hashlib.sha256(
            json.dumps(
                previous,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        actual_committed_sha = hashlib.sha256(
            json.dumps(
                committed,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if (
            not expected_previous_sha
            or not hmac.compare_digest(actual_previous_sha, expected_previous_sha)
            or not hmac.compare_digest(actual_committed_sha, expected_previous_sha)
        ):
            return {}
        try:
            pending_generation = int(pending.get("generation"))
            previous_generation = int(previous.get("generation"))
            pending_base_offset = int(pending.get("source_base_offset"))
            previous_base_offset = int(previous.get("source_base_offset"))
        except (TypeError, ValueError):
            return {}
        if pending_generation != previous_generation or pending_base_offset != previous_base_offset:
            return {}
        pending_source_path = str(pending.get("source_path") or "")
        previous_source_path = str(previous.get("source_path") or "")
        if not pending_source_path or pending_source_path != previous_source_path:
            return {}
        source = Path(pending_source_path).expanduser()
        if not archive.is_file() or not source.is_file():
            return {}
        try:
            source_stat = source.stat()
            actual_size = int(archive.stat().st_size)
            size_before = int(pending.get("segment_size_before"))
            target_size = int(pending.get("segment_size"))
            base_offset = int(previous.get("source_base_offset"))
        except (OSError, TypeError, ValueError):
            return {}
        available = int(source_stat.st_size) - base_offset
        if actual_size < size_before or actual_size > target_size or actual_size > available:
            return {}
        prefix_ok, _prefix_status = _verify_generation_prefix(source, previous, source_stat)
        if not prefix_ok:
            return {}
        append_length = target_size - size_before
        expected_append_sha = str(pending.get("append_sha256") or "").lower()
        actual_append_sha = _sha256_range(
            source,
            base_offset + size_before,
            append_length,
        )
        if (
            append_length <= 0
            or len(expected_append_sha) != 64
            or not actual_append_sha
            or not hmac.compare_digest(actual_append_sha, expected_append_sha)
            or not _same_stat_snapshot(source, source_stat)
        ):
            return {}
        matched, mismatch = _first_mismatch_offset(
            source,
            archive,
            source_start=base_offset,
            archive_start=0,
            length=actual_size,
        )
        if not matched or mismatch is not None or not _same_stat_snapshot(source, source_stat):
            return {}
        recovered_bytes_appended = 0
        recovered_lines_appended = 0
        if actual_size < target_size:
            remaining = target_size - actual_size
            try:
                with source.open("rb") as source_handle, archive.open("ab") as archive_handle:
                    source_handle.seek(base_offset + actual_size)
                    while remaining:
                        chunk = source_handle.read(min(CHUNK_SIZE, remaining))
                        if not chunk:
                            return {}
                        archive_handle.write(chunk)
                        recovered_bytes_appended += len(chunk)
                        recovered_lines_appended += chunk.count(b"\n")
                        remaining -= len(chunk)
                    archive_handle.flush()
                    os.fsync(archive_handle.fileno())
                actual_size = int(archive.stat().st_size)
            except OSError:
                return {}
            if actual_size != target_size or not _same_stat_snapshot(source, source_stat):
                return {}
        recovered = {
            **previous,
            "state": "committed",
            "segment_size": actual_size,
            "source_covered_bytes": base_offset + actual_size,
            "source_snapshot_size": int(source_stat.st_size),
            "source_snapshot_mtime_ns": int(source_stat.st_mtime_ns),
            "recovered_from_pending": True,
            "recovered_operation": "append_generation",
            "recovered_partial_append": recovered_bytes_appended > 0,
            "recovered_bytes_appended": recovered_bytes_appended,
            "recovered_lines_appended": recovered_lines_appended,
        }
        recovered.pop("segment_sha256", None)
        try:
            _atomic_json_write(descriptor_path, recovered)
            pending_path.unlink()
        except OSError:
            return {}
        return recovered
    if not archive.is_file():
        return {}
    try:
        expected_size = int(pending.get("segment_size"))
    except (TypeError, ValueError):
        return {}
    expected_sha = str(pending.get("segment_sha256") or "")
    try:
        actual_size = archive.stat().st_size
    except OSError:
        return {}
    if actual_size != expected_size or not expected_sha or _sha256(archive) != expected_sha:
        return {}
    committed = {**pending, "state": "committed", "recovered_from_pending": True}
    if not _generation_descriptor_bound_to_archive(
        committed,
        archive,
        require_current_size=True,
    ):
        return {}
    try:
        _atomic_json_write(descriptor_path, committed)
        pending_path.unlink()
    except OSError:
        return {}
    return committed


def load_generation_descriptor(
    archive_path: str | Path,
    *,
    recover_pending: bool = False,
) -> dict[str, Any]:
    """Read a committed descriptor; transaction recovery is explicit and writeful."""
    archive = Path(archive_path).expanduser()
    payload = (
        _recover_pending_generation(archive)
        if recover_pending
        else _load_json_object(_generation_descriptor_path(archive))
    )
    if not payload or not _generation_descriptor_bound_to_archive(
        payload,
        archive,
        require_current_size=True,
    ):
        return {}
    return payload


def generation_descriptor_path(archive_path: str | Path) -> Path:
    return _generation_descriptor_path(Path(archive_path).expanduser())


def _sha256_range(path: Path, start: int, length: int) -> str:
    if start < 0 or length < 0:
        return ""
    digest = hashlib.sha256()
    remaining = int(length)
    try:
        with path.open("rb") as handle:
            handle.seek(int(start))
            while remaining:
                chunk = handle.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    return ""
                digest.update(chunk)
                remaining -= len(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _first_mismatch_offset(
    source: Path,
    archive: Path,
    *,
    source_start: int,
    archive_start: int,
    length: int,
) -> tuple[bool, int | None]:
    """Compare two ranges and return the first relative mismatch."""
    remaining = max(0, int(length))
    relative = 0
    try:
        with source.open("rb") as source_handle, archive.open("rb") as archive_handle:
            source_handle.seek(max(0, int(source_start)))
            archive_handle.seek(max(0, int(archive_start)))
            while remaining:
                size = min(CHUNK_SIZE, remaining)
                source_chunk = source_handle.read(size)
                archive_chunk = archive_handle.read(size)
                if len(source_chunk) != len(archive_chunk):
                    common = min(len(source_chunk), len(archive_chunk))
                    mismatch = next(
                        (index for index, pair in enumerate(zip(source_chunk[:common], archive_chunk[:common])) if pair[0] != pair[1]),
                        common,
                    )
                    return False, relative + mismatch
                mismatch = next(
                    (index for index, pair in enumerate(zip(source_chunk, archive_chunk)) if pair[0] != pair[1]),
                    None,
                )
                if mismatch is not None:
                    return False, relative + mismatch
                relative += len(source_chunk)
                remaining -= size
    except OSError:
        return False, -1
    return True, None


def _line_start_before(path: Path, offset: int, lower_bound: int = 0) -> int | None:
    """Find a bounded JSONL line start without loading the whole source."""
    target = max(int(lower_bound), int(offset))
    if target <= lower_bound:
        return int(lower_bound)
    cursor = target
    scanned = 0
    while cursor > lower_bound and scanned < GENERATION_MAX_JSON_LINE_BYTES:
        start = max(int(lower_bound), cursor - CHUNK_SIZE)
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                data = handle.read(cursor - start)
        except OSError:
            return None
        index = data.rfind(b"\n")
        if index >= 0:
            return start + index + 1
        scanned += len(data)
        cursor = start
    return int(lower_bound) if cursor == lower_bound else None


def _complete_jsonl_line(path: Path, offset: int) -> bytes | None:
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, int(offset)))
            data = handle.readline(GENERATION_MAX_JSON_LINE_BYTES + 1)
    except OSError:
        return None
    if not data or len(data) > GENERATION_MAX_JSON_LINE_BYTES or not data.endswith(b"\n"):
        return None
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError):
        return None
    return data if isinstance(value, dict) else None


def _last_complete_jsonl_end(path: Path, lower_bound: int, upper_bound: int) -> int | None:
    """Return the last newline boundary without consuming an in-flight JSONL tail."""
    lower = max(0, int(lower_bound))
    upper = max(lower, int(upper_bound))
    if upper == lower:
        return lower
    cursor = upper
    scanned = 0
    while cursor > lower and scanned <= GENERATION_MAX_JSON_LINE_BYTES:
        start = max(lower, cursor - CHUNK_SIZE)
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                data = handle.read(cursor - start)
        except OSError:
            return None
        index = data.rfind(b"\n")
        if index >= 0:
            return start + index + 1
        scanned += len(data)
        cursor = start
    return lower if cursor == lower else None


def _divergence_boundary(
    source: Path,
    archive: Path,
    *,
    source_start: int,
    mismatch_relative: int,
) -> tuple[int | None, dict[str, Any]]:
    mismatch_source_offset = int(source_start) + int(mismatch_relative)
    boundary = _line_start_before(source, mismatch_source_offset, lower_bound=source_start)
    if boundary is None or boundary < source_start:
        return None, {"status": "line_boundary_not_found"}
    source_line = _complete_jsonl_line(source, boundary)
    archive_line = _complete_jsonl_line(archive, boundary - source_start)
    if source_line is None or archive_line is None:
        return None, {"status": "line_boundary_not_proven"}
    try:
        archive_size = int(archive.stat().st_size)
    except OSError:
        return None, {"status": "divergence_witness_not_stable"}
    window_length = min(GENERATION_WITNESS_BYTES, archive_size)
    window_offset = min(
        max(0, mismatch_relative - (window_length // 2)),
        max(0, archive_size - window_length),
    )
    source_sha = _sha256_range(source, source_start + window_offset, window_length)
    archive_sha = _sha256_range(archive, window_offset, window_length)
    if not source_sha or not archive_sha or source_sha == archive_sha:
        return None, {"status": "divergence_witness_not_stable"}
    return boundary, {
        "status": "proven",
        "mismatch_source_offset": mismatch_source_offset,
        "mismatch_archive_offset": mismatch_relative,
        "line_start_source_offset": boundary,
        "window_offset": window_offset,
        "window_length": window_length,
        "source_sha256": source_sha,
        "archive_sha256": archive_sha,
    }


def _verify_generation_prefix(source: Path, descriptor: dict[str, Any], source_stat: os.stat_result) -> tuple[bool, str]:
    raw_base_offset = descriptor.get("source_base_offset", -1)
    base_offset = int(raw_base_offset if raw_base_offset is not None else -1)
    expected = str(descriptor.get("source_prefix_sha256") or "")
    if base_offset < 0 or len(expected) != 64:
        return False, "generation_prefix_proof_missing"
    actual = _sha256_range(source, 0, base_offset)
    if not actual:
        return False, "generation_prefix_unreadable"
    if not hmac.compare_digest(actual, expected.lower()):
        return False, "generation_prefix_changed"
    if not _same_stat_snapshot(source, source_stat):
        return False, "source_changed_during_generation_prefix_probe"
    return True, "generation_prefix_verified"


def _next_generation_path(base: Path) -> tuple[Path, int]:
    base = _archive_base_path(base)
    candidates = _archive_segment_candidates(base)
    max_index = max((_segment_index(candidate, base) for candidate in candidates), default=0)
    max_generation = 0
    for candidate in candidates:
        descriptor = load_generation_descriptor(candidate)
        try:
            max_generation = max(max_generation, int(descriptor.get("generation", 0) or 0))
        except (TypeError, ValueError):
            pass
    index = max(max_index, max_generation) + 1
    while True:
        candidate = base.with_name(f"{base.stem}.seg{index}{base.suffix}")
        if not candidate.exists() and not _generation_descriptor_path(candidate).exists():
            return candidate, index
        index += 1


def _create_divergence_generation(
    source: Path,
    archive: Path,
    *,
    source_stat: os.stat_result,
    source_base_offset: int = 0,
    predecessor_descriptor: dict[str, Any] | None = None,
    source_inode: int | None = None,
    dry_run: bool = False,
    reason: str = "source_divergence",
    mismatch_hint: int | None = None,
    forced_boundary: int | None = None,
    forced_witness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze an archive and continue from a proven JSONL line boundary."""
    try:
        archive_stat = archive.stat()
    except OSError as exc:
        return {
            "ok": False,
            "status": "source_divergence_generation_fail_closed",
            "generation_failure": "predecessor_unavailable",
            "error": str(exc),
        }
    source_size = int(source_stat.st_size)
    archive_size = int(archive_stat.st_size)
    base_offset = max(0, int(source_base_offset))
    available = source_size - base_offset
    if forced_boundary is None and available < archive_size:
        return {
            "ok": True,
            "status": "source_regression_raw_retained",
            "source_regression": True,
            "source_size": source_size,
            "archive_size_before": archive_size,
            "source_base_offset": base_offset,
            "write_performed": False,
        }
    if forced_boundary is not None:
        boundary = max(0, int(forced_boundary))
        witness = dict(forced_witness or {})
        witness.setdefault("status", "proven_forced_generation_boundary")
        witness.setdefault("line_start_source_offset", boundary)
        mismatch_relative = None
    else:
        if mismatch_hint is not None:
            matched, actual_mismatch = _first_mismatch_offset(
                source,
                archive,
                source_start=base_offset,
                archive_start=0,
                length=min(archive_size, available),
            )
            mismatch_relative = None if matched else actual_mismatch
        else:
            _matched, mismatch_relative = _first_mismatch_offset(
                source,
                archive,
                source_start=base_offset,
                archive_start=0,
                length=min(archive_size, available),
            )
        if mismatch_relative is None:
            return {
                "ok": True,
                "status": "generation_not_needed",
                "source_divergence": False,
                "source_size": source_size,
                "archive_size_before": archive_size,
                "source_base_offset": base_offset,
                "write_performed": False,
            }
        if mismatch_relative < 0:
            return {
                "ok": False,
                "status": "source_divergence_generation_fail_closed",
                "source_divergence": True,
                "generation_failure": "divergence_compare_failed",
                "source_size": source_size,
                "archive_size_before": archive_size,
                "source_base_offset": base_offset,
                "write_performed": False,
            }
        boundary, witness = _divergence_boundary(
            source,
            archive,
            source_start=base_offset,
            mismatch_relative=mismatch_relative,
        )
    if boundary is None:
        return {
            "ok": False,
            "status": "source_divergence_generation_fail_closed",
            "source_divergence": True,
            "generation_failure": witness.get("status", "line_boundary_not_proven"),
            "source_size": source_size,
            "archive_size_before": archive_size,
            "source_base_offset": base_offset,
            "write_performed": False,
        }
    prefix_sha = _sha256_range(source, 0, boundary)
    if not prefix_sha or not _same_stat_snapshot(source, source_stat):
        return {
            "ok": False,
            "status": "source_divergence_generation_fail_closed",
            "source_divergence": True,
            "generation_failure": "source_changed_during_boundary_probe",
            "source_size": source_size,
            "archive_size_before": archive_size,
            "source_base_offset": boundary,
            "write_performed": False,
        }
    copy_end = _last_complete_jsonl_end(source, boundary, source_size)
    if copy_end is None or copy_end <= boundary:
        return {
            "ok": False,
            "status": "source_divergence_generation_fail_closed",
            "source_divergence": True,
            "generation_failure": "generation_complete_end_not_proven",
            "source_size": source_size,
            "archive_size_before": archive_size,
            "source_base_offset": boundary,
            "write_performed": False,
        }
    predecessor_generation = 0
    if predecessor_descriptor:
        try:
            predecessor_generation = int(predecessor_descriptor.get("generation", 0) or 0)
        except (TypeError, ValueError):
            predecessor_generation = 0
    target, segment_index = _next_generation_path(archive)
    generation = max(predecessor_generation + 1, segment_index)
    base_report = {
        "ok": True,
        "source_divergence": True,
        "generation_started": False,
        "source_size": source_size,
        "archive_size_before": archive_size,
        "source_base_offset": boundary,
        "predecessor": str(archive),
        "generation": generation,
        "generation_path": str(target),
        "generation_descriptor_path": str(_generation_descriptor_path(target)),
        "divergence_witness": witness,
        "write_performed": False,
    }
    if dry_run:
        return {
            **base_report,
            "status": "source_divergence_generation_candidate",
        }

    temp = target.with_name(f"{target.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    segment_hash = hashlib.sha256()
    copied = 0
    lines_copied = 0
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as source_handle, temp.open("xb") as segment_handle:
            source_handle.seek(boundary)
            remaining = copy_end - boundary
            while remaining:
                chunk = source_handle.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    raise OSError("source_ended_before_generation_complete_boundary")
                segment_handle.write(chunk)
                segment_hash.update(chunk)
                copied += len(chunk)
                lines_copied += chunk.count(b"\n")
                remaining -= len(chunk)
            segment_handle.flush()
            os.fsync(segment_handle.fileno())
        if not _same_stat_snapshot(source, source_stat):
            raise OSError("source_changed_during_generation_copy")
        if copied <= 0:
            raise OSError("empty_generation_segment")
        descriptor = {
            "contract": GENERATION_CONTRACT,
            "state": "prepared",
            "generation": generation,
            "predecessor": str(archive),
            "predecessor_generation": predecessor_generation,
            "reason": reason,
            "source_path": str(source),
            "source_inode": int(source_inode or source_stat.st_ino),
            "source_base_offset": boundary,
            "source_prefix_sha256": prefix_sha,
            "source_snapshot_size": source_size,
            "source_snapshot_mtime_ns": int(source_stat.st_mtime_ns),
            "source_covered_bytes": copy_end,
            "segment_path": str(target),
            "segment_size": copied,
            "segment_sha256": segment_hash.hexdigest(),
            "divergence_witness": witness,
            "created_at_ns": time.time_ns(),
        }
        _atomic_json_write(_generation_pending_path(target), descriptor)
        if target.exists():
            raise OSError("generation_target_exists")
        os.rename(temp, target)
        _fsync_parent(target)
        committed = {**descriptor, "state": "committed"}
        _atomic_json_write(_generation_descriptor_path(target), committed)
        try:
            _generation_pending_path(target).unlink()
        except OSError:
            pass
        return {
            **base_report,
            "status": "source_divergence_generation_started",
            "generation_started": True,
            "archive_path": str(target),
            "archive_size_after": copied,
            "bytes_copied": copied,
            "bytes_appended": copied,
            "lines_appended": lines_copied,
            "source_covered_bytes": copy_end,
            "write_performed": True,
            "generation_descriptor": committed,
        }
    except (OSError, ValueError, TypeError) as exc:
        return {
            **base_report,
            "ok": False,
            "status": "source_divergence_generation_fail_closed",
            "generation_failure": str(exc),
        }
    finally:
        try:
            temp.unlink()
        except OSError:
            pass


def _append_generation_source(
    source: Path,
    archive: Path,
    descriptor: dict[str, Any],
    *,
    source_stat: os.stat_result,
    source_inode: int | None,
    dry_run: bool,
    compute_sha256: bool,
    continue_on_divergence: bool,
) -> dict[str, Any]:
    raw_base_offset = descriptor.get("source_base_offset", -1)
    base_offset = int(raw_base_offset if raw_base_offset is not None else -1)
    archive_stat = archive.stat()
    archive_size = int(archive_stat.st_size)
    source_size = int(source_stat.st_size)
    base = {
        "ok": True,
        "contract": CONTRACT,
        "source_path": str(source),
        "archive_path": str(archive),
        "source_exists": True,
        "source_size": source_size,
        "archive_size_before": archive_size,
        "archive_size_after": archive_size,
        "write_performed": False,
        "dry_run": bool(dry_run),
        "raw_shrink_performed": False,
        "source_regression": False,
        "source_divergence": True,
        "source_identity_rebound": False,
        "generation_active": True,
        "generation": int(descriptor.get("generation", 0) or 0),
        "source_base_offset": base_offset,
        "predecessor": descriptor.get("predecessor", ""),
        "prefix_verification": "not_applicable",
    }
    if base_offset < 0:
        return {**base, "ok": False, "status": "source_divergence_generation_fail_closed", "generation_failure": "invalid_source_base_offset"}
    try:
        descriptor_inode = int(descriptor.get("source_inode", 0) or 0)
    except (TypeError, ValueError):
        descriptor_inode = 0
    observed_inode = int(source_inode or source_stat.st_ino or 0)
    if descriptor_inode and observed_inode and descriptor_inode != observed_inode:
        generation = _create_divergence_generation(
            source,
            archive,
            source_stat=source_stat,
            source_base_offset=0,
            predecessor_descriptor=descriptor,
            source_inode=observed_inode,
            dry_run=dry_run,
            reason="source_inode_rotation_after_generation",
            forced_boundary=0,
            forced_witness={
                "status": "proven_source_inode_rotation_after_generation",
                "predecessor_source_inode": descriptor_inode,
                "successor_source_inode": observed_inode,
            },
        )
        return {**base, **generation, "source_identity_rotated": True}
    prefix_ok, prefix_status = _verify_generation_prefix(source, descriptor, source_stat)
    base["prefix_verification"] = prefix_status
    if not prefix_ok:
        if continue_on_divergence and prefix_status == "generation_prefix_changed":
            generation = _create_divergence_generation(
                source,
                archive,
                source_stat=source_stat,
                source_base_offset=0,
                predecessor_descriptor=descriptor,
                source_inode=source_inode,
                dry_run=dry_run,
                reason="source_prefix_divergence_after_generation",
                forced_boundary=0,
                forced_witness={
                    "status": "proven_generation_prefix_divergence",
                    "prior_source_base_offset": base_offset,
                    "expected_source_prefix_sha256": descriptor.get("source_prefix_sha256", ""),
                },
            )
            return {**base, **generation}
        return {**base, "ok": False, "status": "source_divergence_generation_fail_closed", "generation_failure": prefix_status}
    source_available = source_size - base_offset
    if source_available < archive_size:
        return {
            **base,
            "status": "source_regression_raw_retained",
            "source_regression": True,
            "source_divergence": False,
            "retained_bytes": archive_size,
        }
    complete_end = _last_complete_jsonl_end(source, base_offset, source_size)
    if complete_end is None:
        return {
            **base,
            "ok": False,
            "status": "source_divergence_generation_fail_closed",
            "generation_failure": "generation_complete_end_not_proven",
        }
    available = complete_end - base_offset
    if available < archive_size:
        return {
            **base,
            "ok": False,
            "status": "source_divergence_generation_fail_closed",
            "generation_failure": "generation_archive_exceeds_complete_source_boundary",
        }
    matched, mismatch_relative = _first_mismatch_offset(
        source,
        archive,
        source_start=base_offset,
        archive_start=0,
        length=archive_size,
    )
    if not matched:
        if not continue_on_divergence:
            return {
                **base,
                "status": "source_divergence_raw_retained",
                "retained_bytes": archive_size,
                "prefix_verification": "generation_full_fail_closed",
            }
        generation = _create_divergence_generation(
            source,
            archive,
            source_stat=source_stat,
            source_base_offset=base_offset,
            predecessor_descriptor=descriptor,
            source_inode=source_inode,
            dry_run=dry_run,
            reason="source_divergence_after_generation",
            mismatch_hint=mismatch_relative,
        )
        return {**base, **generation}
    if available == archive_size:
        return {
            **base,
            "status": (
                "up_to_date"
                if complete_end == source_size
                else "waiting_for_complete_jsonl_line"
            ),
            "source_divergence": True,
            "source_covered_bytes": complete_end,
        }
    if dry_run:
        return {
            **base,
            "status": "would_append_generation",
            "bytes_appended": available - archive_size,
            "archive_size_after": available,
            "source_covered_bytes": complete_end,
        }
    remaining = available - archive_size
    appended = 0
    lines_appended = 0
    append_sha = _sha256_range(
        source,
        base_offset + archive_size,
        remaining,
    )
    if not append_sha or not _same_stat_snapshot(source, source_stat):
        return {
            **base,
            "ok": False,
            "status": "source_divergence_generation_fail_closed",
            "generation_failure": "source_changed_during_generation_append_witness",
        }
    descriptor_sha = hashlib.sha256(
        json.dumps(
            descriptor,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    pending = {
        "contract": GENERATION_CONTRACT,
        "state": "prepared",
        "operation": "append_generation",
        "generation": int(descriptor.get("generation", 0) or 0),
        "segment_path": str(archive),
        "segment_size_before": archive_size,
        "segment_size": available,
        "source_path": str(source),
        "source_base_offset": base_offset,
        "source_snapshot_size": source_size,
        "source_snapshot_mtime_ns": int(source_stat.st_mtime_ns),
        "append_sha256": append_sha,
        "previous_descriptor": descriptor,
        "previous_descriptor_sha256": descriptor_sha,
    }
    try:
        _atomic_json_write(_generation_pending_path(archive), pending)
        with source.open("rb") as source_handle, archive.open("ab") as archive_handle:
            source_handle.seek(base_offset + archive_size)
            while remaining:
                chunk = source_handle.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    break
                archive_handle.write(chunk)
                appended += len(chunk)
                lines_appended += chunk.count(b"\n")
                remaining -= len(chunk)
            archive_handle.flush()
            os.fsync(archive_handle.fileno())
    except OSError as exc:
        return {
            **base,
            "ok": False,
            "status": "source_divergence_generation_fail_closed",
            "generation_failure": f"generation_append_interrupted:{exc}",
            "archive_size_after": archive.stat().st_size if archive.exists() else archive_size,
            "bytes_appended": appended,
        }
    final_size = archive.stat().st_size
    if not _same_stat_snapshot(source, source_stat) or final_size != available:
        return {
            **base,
            "ok": False,
            "status": "source_divergence_generation_fail_closed",
            "generation_failure": "source_changed_during_generation_append",
            "archive_size_after": final_size,
            "bytes_appended": appended,
        }
    descriptor = dict(descriptor)
    descriptor["segment_size"] = final_size
    descriptor["source_covered_bytes"] = base_offset + final_size
    descriptor["source_snapshot_size"] = source_size
    descriptor["source_snapshot_mtime_ns"] = int(source_stat.st_mtime_ns)
    descriptor.pop("segment_sha256", None)
    try:
        _atomic_json_write(_generation_descriptor_path(archive), descriptor)
        _generation_pending_path(archive).unlink()
    except OSError as exc:
        return {
            **base,
            "ok": False,
            "status": "source_divergence_generation_fail_closed",
            "generation_failure": f"generation_descriptor_commit_interrupted:{exc}",
            "archive_size_after": final_size,
            "bytes_appended": appended,
        }
    return {
        **base,
        "status": "appended_generation",
        "archive_size_after": final_size,
        "bytes_appended": appended,
        "lines_appended": lines_appended,
        "write_performed": appended > 0,
        "source_covered_bytes": base_offset + final_size,
    }


def _forget_divergence_witness(source: Path, archive: Path) -> None:
    key = _divergence_witness_key(source, archive)
    with _DIVERGENCE_WITNESS_LOCK:
        _DIVERGENCE_WITNESS_CACHE.pop(key, None)


def _remember_divergence_witness(
    source: Path,
    archive: Path,
    archive_size: int,
    mismatch_offset: int,
) -> None:
    window_length = min(DIVERGENCE_WITNESS_BYTES, max(0, int(archive_size)))
    if not window_length:
        return
    window_offset = min(
        max(0, int(mismatch_offset) - (window_length // 2)),
        max(0, int(archive_size) - window_length),
    )
    source_sha256 = _window_sha256(source, window_offset, window_length)
    archive_sha256 = _window_sha256(archive, window_offset, window_length)
    if not source_sha256 or not archive_sha256 or source_sha256 == archive_sha256:
        return
    key = _divergence_witness_key(source, archive)
    witness = {
        "archive_size": int(archive_size),
        "offset": window_offset,
        "length": window_length,
        "source_sha256": source_sha256,
        "archive_sha256": archive_sha256,
    }
    with _DIVERGENCE_WITNESS_LOCK:
        _DIVERGENCE_WITNESS_CACHE[key] = witness
        _DIVERGENCE_WITNESS_CACHE.move_to_end(key)
        while len(_DIVERGENCE_WITNESS_CACHE) > DIVERGENCE_WITNESS_CACHE_LIMIT:
            _DIVERGENCE_WITNESS_CACHE.popitem(last=False)


def _cached_divergence_still_visible(source: Path, archive: Path, archive_size: int) -> bool:
    key = _divergence_witness_key(source, archive)
    with _DIVERGENCE_WITNESS_LOCK:
        witness = dict(_DIVERGENCE_WITNESS_CACHE.get(key, {}))
    witness_archive_size = int(witness.get("archive_size", -1)) if witness else -1
    current_archive_size = int(archive_size)
    # A retained divergence remains valid when the raw archive only appends.
    # Shrinkage or an archive that no longer contains the witness must fall
    # back to the bounded prefix check so the result stays fail-closed.
    if not witness or current_archive_size < witness_archive_size:
        _forget_divergence_witness(source, archive)
        return False
    offset = int(witness.get("offset", 0) or 0)
    length = int(witness.get("length", 0) or 0)
    if (
        offset < 0
        or not length
        or offset + length > witness_archive_size
        or offset + length > current_archive_size
    ):
        _forget_divergence_witness(source, archive)
        return False
    source_sha256 = _window_sha256(source, offset, length)
    archive_sha256 = _window_sha256(archive, offset, length)
    still_visible = (
        source_sha256 == witness.get("source_sha256")
        and archive_sha256 == witness.get("archive_sha256")
        and source_sha256 != archive_sha256
    )
    if still_visible:
        _increment_diagnostics(divergence_witness_hit_count=1)
        with _DIVERGENCE_WITNESS_LOCK:
            if key in _DIVERGENCE_WITNESS_CACHE:
                _DIVERGENCE_WITNESS_CACHE.move_to_end(key)
        return True
    _forget_divergence_witness(source, archive)
    return False


def cached_divergence_witness_visible(
    source_path: str | Path,
    archive_path: str | Path,
    archive_size: int | None = None,
) -> bool:
    """Recheck a known mismatch window without rescanning the full prefix."""
    source = Path(source_path).expanduser()
    archive = Path(archive_path).expanduser()
    if archive_size is None:
        try:
            archive_size = archive.stat().st_size
        except OSError:
            return False
    return _cached_divergence_still_visible(source, archive, int(archive_size or 0))


def _prefix_matches(
    source: Path,
    archive: Path,
    length: int,
    *,
    source_hasher_out: dict[str, Any] | None = None,
) -> bool:
    if _cached_divergence_still_visible(source, archive, length):
        return False
    remaining = max(0, int(length))
    offset = 0
    source_bytes_read = 0
    archive_bytes_read = 0
    source_hasher = hashlib.sha256()
    proof_blocks: list[dict[str, Any]] = []
    _increment_diagnostics(full_prefix_scan_count=1)
    try:
        with source.open("rb") as src, archive.open("rb") as raw:
            while remaining:
                size = min(CHUNK_SIZE, remaining)
                source_chunk = src.read(size)
                archive_chunk = raw.read(size)
                source_bytes_read += len(source_chunk)
                archive_bytes_read += len(archive_chunk)
                source_hasher.update(source_chunk)
                if source_chunk != archive_chunk:
                    mismatch = next(
                        (
                            index
                            for index, (source_byte, archive_byte) in enumerate(zip(source_chunk, archive_chunk))
                            if source_byte != archive_byte
                        ),
                        0,
                    )
                    _remember_divergence_witness(source, archive, length, offset + mismatch)
                    return False
                proof_blocks.append({
                    "offset": offset,
                    "length": len(source_chunk),
                    "sha256": hashlib.sha256(source_chunk).hexdigest(),
                })
                remaining -= size
                offset += size
    finally:
        _increment_diagnostics(
            full_prefix_source_bytes=source_bytes_read,
            full_prefix_archive_bytes=archive_bytes_read,
        )
    _forget_divergence_witness(source, archive)
    if isinstance(source_hasher_out, dict):
        source_hasher_out["hasher"] = source_hasher
        source_hasher_out["proof_blocks"] = proof_blocks
    return True


def _segment_index(path: Path, base: Path) -> int:
    if path == base:
        return 0
    match = re.fullmatch(
        re.escape(base.stem) + r"\.seg(\d+)" + re.escape(base.suffix),
        path.name,
    )
    return int(match.group(1)) if match else 0


def _archive_base_path(path: Path) -> Path:
    match = re.fullmatch(r"(.+)\.seg\d+", path.stem)
    if not match:
        return path
    return path.with_name(match.group(1) + path.suffix)


def _is_archive_segment(path: Path, base: Path) -> bool:
    if path == base:
        return True
    return bool(re.fullmatch(
        re.escape(base.stem) + r"\.seg\d+" + re.escape(base.suffix),
        path.name,
    ))


def _archive_segment_candidates(
    base: Path,
    *,
    directory_cache: dict[str, dict[str, tuple[Path, ...]]] | None = None,
) -> list[Path]:
    base = _archive_base_path(base)
    candidates = [base]
    if base.parent.exists():
        if directory_cache is None:
            candidates.extend(
                path
                for path in base.parent.glob(f"{base.stem}.seg*{base.suffix}")
                if _is_archive_segment(path, base)
            )
        else:
            directory_key = os.path.normcase(os.path.abspath(base.parent))
            index = directory_cache.get(directory_key)
            if index is None:
                grouped: dict[str, list[Path]] = {}
                try:
                    entries = (path for path in base.parent.iterdir() if path.is_file())
                except OSError:
                    entries = ()
                for path in entries:
                    archive_base = _archive_base_path(path)
                    grouped.setdefault(os.path.normcase(archive_base.name), []).append(path)
                index = {
                    name: tuple(paths)
                    for name, paths in grouped.items()
                }
                directory_cache[directory_key] = index
            candidates.extend(index.get(os.path.normcase(base.name), ()))
    return sorted(
        {
            path
            for path in candidates
            if _is_archive_segment(path, base) and path.is_file()
        },
        key=lambda path: _segment_index(path, base),
    )


def archive_generation_chain(archive_path: str | Path) -> list[dict[str, Any]]:
    """Return ordered generation metadata without reading archived content."""
    base = _archive_base_path(Path(archive_path).expanduser())
    chain: list[dict[str, Any]] = []
    for candidate in _archive_segment_candidates(base):
        descriptor = load_generation_descriptor(candidate)
        descriptor_path = _generation_descriptor_path(candidate)
        pending_path = _generation_pending_path(candidate)
        chain.append({
            "archive_path": str(candidate),
            "segment_index": _segment_index(candidate, base),
            "generation": int(descriptor.get("generation", 0) or 0),
            "source_base_offset": int(descriptor.get("source_base_offset", 0) or 0),
            "predecessor": str(descriptor.get("predecessor") or ""),
            "reason": str(descriptor.get("reason") or "legacy_or_inode_rotation"),
            "descriptor_path": str(descriptor_path) if descriptor_path.exists() else "",
            "descriptor_present": descriptor_path.exists(),
            "descriptor_valid": bool(descriptor),
            "pending_path": str(pending_path) if pending_path.exists() else "",
            "pending_present": pending_path.exists(),
        })
    return chain


def select_archive_segment_metadata_only(
    archive_path: str | Path,
    source_inode: int | None,
    *,
    directory_cache: dict[str, dict[str, tuple[Path, ...]]] | None = None,
) -> dict[str, Any]:
    """Select the best existing segment without reading source or raw bodies.

    This is intentionally weaker than :func:`select_archive_segment`. It is for
    bounded status pages that may inspect small metadata/generation sidecars but
    must not perform prefix comparison. Callers must keep an unproven selection
    fail-closed instead of treating path discovery as content continuity proof.
    """
    requested = Path(archive_path).expanduser()
    base = _archive_base_path(requested)
    candidates = _archive_segment_candidates(base, directory_cache=directory_cache)
    inode = int(source_inode or 0)
    details: list[dict[str, Any]] = []
    for candidate in candidates:
        descriptor_path = _generation_descriptor_path(candidate)
        pending_path = _generation_pending_path(candidate)
        descriptor = load_generation_descriptor(candidate)
        meta_path = Path(str(candidate) + ".meta.json")
        meta = _load_json_object(meta_path)
        try:
            meta_inode = int(meta.get("source_inode", 0) or 0)
        except (TypeError, ValueError):
            meta_inode = 0
        details.append({
            "archive_path": candidate,
            "segment_index": _segment_index(candidate, base),
            "descriptor": descriptor,
            "descriptor_present": descriptor_path.exists(),
            "descriptor_valid": bool(descriptor),
            "pending_present": pending_path.exists(),
            "metadata": meta,
            "metadata_present": meta_path.exists(),
            "metadata_source_inode": meta_inode,
        })

    blockers = [
        item for item in details
        if item["pending_present"]
        or (item["descriptor_present"] and not item["descriptor_valid"])
    ]
    active_generations = [item for item in details if item["descriptor_valid"]]
    inode_matches = [
        item for item in details
        if inode and item["metadata_source_inode"] == inode
    ]
    if blockers:
        selected = blockers[-1]
        selection_status = "generation_blocker"
    elif active_generations:
        selected = max(
            active_generations,
            key=lambda item: (
                int(item["descriptor"].get("generation", 0) or 0),
                int(item["segment_index"]),
            ),
        )
        selection_status = "active_generation_descriptor"
    elif inode_matches:
        selected = inode_matches[-1]
        selection_status = "source_inode_sidecar"
    elif len(details) == 1 and not details[0]["metadata_present"]:
        selected = details[0]
        selection_status = "single_legacy_archive_unverified"
    elif details:
        selected = details[-1]
        selection_status = "latest_retained_archive_unverified"
    else:
        selected = {
            "archive_path": base,
            "segment_index": 0,
            "descriptor": {},
            "descriptor_present": False,
            "descriptor_valid": False,
            "pending_present": False,
            "metadata": {},
            "metadata_present": False,
            "metadata_source_inode": 0,
        }
        selection_status = "archive_missing"

    return {
        **selected,
        "retained_archive_path": details[-1]["archive_path"] if details else base,
        "selection_status": selection_status,
        "selection_proven_by_metadata": selection_status in {
            "active_generation_descriptor",
            "source_inode_sidecar",
        },
        "source_inode_match": bool(
            inode and int(selected.get("metadata_source_inode", 0) or 0) == inode
        ),
        "generation_descriptor_incomplete": bool(blockers),
        "candidate_count": len(details),
        "body_read_performed": False,
    }


def _latest_generation_candidate(base: Path) -> Path | None:
    candidates: list[tuple[int, int, Path]] = []
    for candidate in _archive_segment_candidates(base):
        descriptor = load_generation_descriptor(candidate)
        if not descriptor:
            continue
        candidates.append((
            int(descriptor.get("generation", 0) or 0),
            _segment_index(candidate, _archive_base_path(base)),
            candidate,
        ))
    return max(candidates, key=lambda item: (item[0], item[1]))[2] if candidates else None


def _source_inode_from_meta(archive: Path) -> int:
    try:
        payload = json.loads(Path(str(archive) + ".meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return 0
    try:
        return int(payload.get("source_inode") or 0)
    except (AttributeError, TypeError, ValueError):
        return 0


def _select_archive_segment_detail(
    archive_path: str | Path,
    source_inode: int | None,
    source_path: str | Path | None = None,
) -> tuple[Path, bool]:
    """Choose a segment and distinguish inode drift from content rotation."""
    base = _archive_base_path(Path(archive_path).expanduser())
    inode = int(source_inode or 0)
    if not inode:
        return base, False

    candidates = _archive_segment_candidates(base)
    active_generation = _latest_generation_candidate(base)
    if active_generation is not None:
        return active_generation, False
    for candidate in reversed(candidates):
        if _source_inode_from_meta(candidate) == inode:
            return candidate, False
    if not base.exists():
        return base, False
    # Legacy archives may predate the source-inode sidecar. Preserve that
    # single archive until an identity-bearing write establishes rotation data.
    if len(candidates) == 1 and not Path(str(base) + ".meta.json").exists():
        return base, False

    source = Path(source_path).expanduser() if source_path else None
    if source is not None and source.is_file():
        try:
            source_stat = source.stat()
        except OSError:
            source_stat = None
        if source_stat is not None:
            for candidate in reversed(candidates):
                try:
                    archive_stat = candidate.stat()
                except OSError:
                    continue
                if archive_stat.st_size > source_stat.st_size:
                    continue
                proof: dict[str, Any] = {}
                if not _prefix_matches(
                    source,
                    candidate,
                    archive_stat.st_size,
                    source_hasher_out=proof,
                ):
                    continue
                hasher = proof.get("hasher")
                _remember_matched_prefix(
                    source,
                    candidate,
                    source_stat,
                    archive_stat,
                    hasher.hexdigest() if hasher is not None else "",
                )
                return candidate, True

    next_index = max((_segment_index(candidate, base) for candidate in candidates), default=0) + 1
    return base.with_name(f"{base.stem}.seg{next_index}{base.suffix}"), False


def select_archive_segment(
    archive_path: str | Path,
    source_inode: int | None,
    source_path: str | Path | None = None,
) -> Path:
    """Keep true source rotations separate while tolerating inode-only drift."""
    return _select_archive_segment_detail(archive_path, source_inode, source_path)[0]


def latest_archive_segment(archive_path: str | Path) -> Path:
    """Return the newest existing segment, falling back to the base archive."""
    base = _archive_base_path(Path(archive_path).expanduser())
    candidates = _archive_segment_candidates(base)
    return candidates[-1] if candidates else base


def _append_source_file_unlocked(
    source_path: str | Path,
    archive_path: str | Path,
    *,
    dry_run: bool = False,
    source_inode: int | None = None,
    compute_sha256: bool = True,
    continue_on_divergence: bool = False,
) -> dict[str, Any]:
    source = Path(source_path).expanduser()
    requested_archive = Path(archive_path).expanduser()
    generation_blocker: Path | None = None
    recovered_generation_appends: list[dict[str, Any]] = []
    if continue_on_divergence and not dry_run:
        for candidate in _archive_segment_candidates(_archive_base_path(requested_archive)):
            recovered = _recover_pending_generation(candidate)
            if recovered.get("recovered_operation") == "append_generation":
                recovered_generation_appends.append(recovered)
    if continue_on_divergence:
        for candidate in _archive_segment_candidates(_archive_base_path(requested_archive)):
            pending_exists = _generation_pending_path(candidate).exists()
            descriptor_exists = _generation_descriptor_path(candidate).exists()
            if pending_exists or (descriptor_exists and not load_generation_descriptor(candidate)):
                generation_blocker = candidate
                break
    if generation_blocker is not None:
        archive, source_identity_rebound = generation_blocker, False
    else:
        archive, source_identity_rebound = _select_archive_segment_detail(
            requested_archive,
            source_inode,
            source,
        )
    source_exists = source.is_file()
    source_stat = source.stat() if source_exists else None
    archive_stat = archive.stat() if archive.exists() else None
    source_size = source_stat.st_size if source_stat is not None else 0
    archive_size = archive_stat.st_size if archive_stat is not None else 0
    base = {
        "ok": True,
        "contract": CONTRACT,
        "source_path": str(source),
        "archive_path": str(archive),
        "source_exists": source_exists,
        "source_size": source_size,
        "archive_size_before": archive_size,
        "archive_size_after": archive_size,
        "write_performed": False,
        "dry_run": bool(dry_run),
        "raw_shrink_performed": False,
        "source_regression": False,
        "source_divergence": False,
        "source_missing": not source_exists,
        "source_identity_rebound": bool(source_identity_rebound),
        "prefix_verification": "not_applicable",
    }
    if generation_blocker is not None:
        return {
            **base,
            "ok": False,
            "status": "source_divergence_generation_fail_closed",
            "source_divergence": True,
            "generation_failure": "pending_generation_recovery_incomplete",
        }
    if not source_exists:
        _forget_matched_prefix(source, archive)
        return {
            **base,
            "ok": archive.exists(),
            "status": "source_regression_raw_retained" if archive.exists() else "source_missing_no_archive",
            "source_regression": archive.exists(),
            "retained_bytes": archive_size,
        }
    generation_descriptor = load_generation_descriptor(archive)
    if generation_descriptor and source_stat is not None:
        result = _append_generation_source(
            source,
            archive,
            generation_descriptor,
            source_stat=source_stat,
            source_inode=source_inode,
            dry_run=dry_run,
            compute_sha256=compute_sha256,
            continue_on_divergence=continue_on_divergence,
        )
        if recovered_generation_appends:
            recovered_bytes = sum(
                int(item.get("recovered_bytes_appended", 0) or 0)
                for item in recovered_generation_appends
            )
            recovered_lines = sum(
                int(item.get("recovered_lines_appended", 0) or 0)
                for item in recovered_generation_appends
            )
            result["pending_generation_recovered"] = True
            result["bytes_appended"] = int(result.get("bytes_appended", 0) or 0) + recovered_bytes
            result["lines_appended"] = int(result.get("lines_appended", 0) or 0) + recovered_lines
            if recovered_bytes:
                result["write_performed"] = True
                if result.get("status") == "waiting_for_complete_jsonl_line":
                    result["incomplete_jsonl_tail_waiting"] = True
                if result.get("status") in {"up_to_date", "waiting_for_complete_jsonl_line"}:
                    result["status"] = "appended_generation"
        return result
    if archive_size > source_size:
        _forget_matched_prefix(source, archive)
        return {
            **base,
            "status": "source_regression_raw_retained",
            "source_regression": True,
            "retained_bytes": archive_size,
        }
    source_hasher = None
    source_sha256 = ""
    prior_proof: dict[str, Any] = {}
    prefix_verification = "not_applicable"
    if archive_size:
        if _cached_divergence_still_visible(source, archive, archive_size):
            _forget_matched_prefix(source, archive)
            if continue_on_divergence and source_stat is not None:
                generation = _create_divergence_generation(
                    source,
                    archive,
                    source_stat=source_stat,
                    source_inode=source_inode,
                    dry_run=dry_run,
                )
                return {**base, **generation}
            return {
                **base,
                "status": "source_divergence_raw_retained",
                "source_divergence": True,
                "retained_bytes": archive_size,
                "prefix_verification": "divergence_witness",
            }
        prefix_matches = bool(
            source_stat is not None
            and archive_stat is not None
            and _cached_prefix_match(source, archive, source_stat, archive_stat)
        )
        if prefix_matches and source_stat is not None and archive_stat is not None:
            source_sha256 = _cached_prefix_sha256(source, archive, source_stat, archive_stat)
            prior_proof = _load_prefix_proof(archive)
            prefix_verification = "exact_stat_cache"
        if (
            not prefix_matches
            and source_stat is not None
            and archive_stat is not None
            and source_size > archive_size
        ):
            prefix_matches, prior_proof = _bounded_prefix_proof_match(
                source,
                archive,
                source_stat,
                archive_stat,
            )
            if prefix_matches:
                prefix_verification = "bounded_checkpoint"
        if not prefix_matches:
            source_hasher_out: dict[str, Any] = {}
            prefix_matches = _prefix_matches(
                source,
                archive,
                archive_size,
                source_hasher_out=source_hasher_out,
            )
            source_hasher = source_hasher_out.get("hasher")
            if prefix_matches and source_stat is not None and archive_stat is not None:
                prior_proof = _full_scan_proof(
                    source_stat,
                    archive_stat,
                    source_hasher_out.get("proof_blocks") or [],
                )
                prefix_verification = "full_verified"
            else:
                prefix_verification = "full_fail_closed"
        if not prefix_matches:
            _forget_matched_prefix(source, archive)
            if continue_on_divergence and source_stat is not None:
                generation = _create_divergence_generation(
                    source,
                    archive,
                    source_stat=source_stat,
                    source_inode=source_inode,
                    dry_run=dry_run,
                )
                return {**base, **generation}
            return {
                **base,
                "status": "source_divergence_raw_retained",
                "source_divergence": True,
                "retained_bytes": archive_size,
                "prefix_verification": prefix_verification,
            }
    if archive.exists() and archive_size == source_size:
        if not source_sha256 and source_hasher is not None:
            source_sha256 = source_hasher.hexdigest()
        if (
            source_stat is not None
            and archive_stat is not None
            and source_sha256
            and _same_stat_snapshot(source, source_stat)
            and _same_stat_snapshot(archive, archive_stat)
        ):
            _remember_matched_prefix(
                source,
                archive,
                source_stat,
                archive_stat,
                source_sha256,
            )
        checksum_fields = _checksum_fields(source, archive, compute_sha256=compute_sha256)
        if (
            compute_sha256
            and checksum_fields.get("source_sha256") != checksum_fields.get("archive_sha256")
        ):
            _forget_matched_prefix(source, archive)
            if continue_on_divergence and source_stat is not None:
                generation = _create_divergence_generation(
                    source,
                    archive,
                    source_stat=source_stat,
                    source_inode=source_inode,
                    dry_run=dry_run,
                )
                return {**base, **generation, **checksum_fields}
            return {
                **base,
                "status": "source_divergence_raw_retained",
                "source_divergence": True,
                "retained_bytes": archive_size,
                **checksum_fields,
            }
        if (
            prefix_verification == "full_verified"
            and source_stat is not None
            and archive_stat is not None
            and not dry_run
        ):
            _write_prefix_proof(
                archive,
                prior_proof,
            )
        return {
            **base,
            "status": "up_to_date",
            "prefix_verification": prefix_verification,
            **checksum_fields,
        }

    if dry_run:
        return {
            **base,
            "status": "would_create" if not archive.exists() else "would_append",
            "bytes_appended": source_size - archive_size,
            "archive_size_after": source_size,
            "prefix_verification": prefix_verification,
        }

    archive.parent.mkdir(parents=True, exist_ok=True)
    mode = "ab" if archive.exists() else "xb"
    if source_hasher is None:
        source_hasher = hashlib.sha256()
    remaining_to_append = max(0, source_size - archive_size)
    with source.open("rb") as src, archive.open(mode) as raw:
        src.seek(archive_size)
        appended = 0
        lines_appended = 0
        while remaining_to_append:
            chunk = src.read(min(CHUNK_SIZE, remaining_to_append))
            if not chunk:
                break
            raw.write(chunk)
            source_hasher.update(chunk)
            appended += len(chunk)
            lines_appended += chunk.count(b"\n")
            remaining_to_append -= len(chunk)
        raw.flush()
        os.fsync(raw.fileno())
    final_archive_stat = archive.stat()
    final_size = final_archive_stat.st_size
    source_sha256 = source_hasher.hexdigest() if final_size == source_size else ""
    checksum_fields = _checksum_fields(source, archive, compute_sha256=compute_sha256)
    proof_sha256 = (
        checksum_fields.get("source_sha256", "")
        if compute_sha256
        else source_sha256
    )
    if (
        source_stat is not None
        and _same_stat_snapshot(source, source_stat)
        and final_size == source_size
        and (
            not compute_sha256
            or checksum_fields.get("source_sha256") == checksum_fields.get("archive_sha256")
        )
    ):
        _remember_matched_prefix(
            source,
            archive,
            source_stat,
            final_archive_stat,
            proof_sha256,
        )
        prefix_proof_written = _refresh_prefix_proof_after_append(
            archive,
            source_stat,
            archive_size,
            archive_stat,
            prior_proof,
        )
    else:
        _forget_matched_prefix(source, archive)
        prefix_proof_written = False
    return {
        **base,
        "status": "created" if archive_size == 0 else "appended",
        "archive_size_after": final_size,
        "bytes_appended": appended,
        "lines_appended": lines_appended,
        "write_performed": appended > 0,
        "prefix_verification": prefix_verification,
        "prefix_proof_written": prefix_proof_written,
        **checksum_fields,
    }


def append_source_file(
    source_path: str | Path,
    archive_path: str | Path,
    *,
    dry_run: bool = False,
    source_inode: int | None = None,
    compute_sha256: bool = True,
    continue_on_divergence: bool = False,
) -> dict[str, Any]:
    if dry_run or not continue_on_divergence:
        return _append_source_file_unlocked(
            source_path,
            archive_path,
            dry_run=dry_run,
            source_inode=source_inode,
            compute_sha256=compute_sha256,
            continue_on_divergence=continue_on_divergence,
        )
    with _exclusive_generation_lock(Path(archive_path).expanduser()):
        return _append_source_file_unlocked(
            source_path,
            archive_path,
            dry_run=False,
            source_inode=source_inode,
            compute_sha256=compute_sha256,
            continue_on_divergence=True,
        )


def append_jsonl_records(
    archive_path: str | Path,
    records: Iterable[dict[str, Any]],
    *,
    id_key: str = "id",
) -> dict[str, Any]:
    archive = Path(archive_path).expanduser()
    incoming = [item for item in records if isinstance(item, dict)]
    existing: list[dict[str, Any]] = []
    if archive.exists():
        for line in archive.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                existing.append(value)

    def record_identity(item: dict[str, Any]) -> str:
        explicit = str(item.get(id_key) or "").strip()
        if explicit:
            return "id:" + explicit
        payload = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    existing_by_id = {record_identity(item): item for item in existing}
    incoming_by_id = {record_identity(item): item for item in incoming}
    mutations = [
        record_id
        for record_id in sorted(existing_by_id.keys() & incoming_by_id.keys())
        if existing_by_id[record_id] != incoming_by_id[record_id]
    ]
    missing_from_source = sorted(existing_by_id.keys() - incoming_by_id.keys())
    additions = [
        item for item in incoming
        if record_identity(item) not in existing_by_id
    ]
    if additions:
        archive.parent.mkdir(parents=True, exist_ok=True)
        with archive.open("a", encoding="utf-8") as handle:
            for item in additions:
                handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return {
        "ok": True,
        "contract": CONTRACT,
        "archive_path": str(archive),
        "status": (
            "appended_with_source_regression_raw_retained"
            if additions and missing_from_source
            else "appended_with_source_divergence_raw_retained"
            if additions and mutations
            else "appended"
            if additions
            else "source_regression_raw_retained"
            if missing_from_source
            else "source_divergence_raw_retained"
            if mutations
            else "up_to_date"
        ),
        "existing_record_count": len(existing),
        "source_record_count": len(incoming),
        "appended_record_count": len(additions),
        "source_missing_record_count": len(missing_from_source),
        "source_mutation_count": len(mutations),
        "source_regression": bool(missing_from_source),
        "source_divergence": bool(mutations),
        "write_performed": bool(additions),
        "raw_shrink_performed": False,
    }


__all__ = [
    "CONTRACT",
    "GENERATION_CONTRACT",
    "append_source_file",
    "append_jsonl_records",
    "archive_generation_chain",
    "generation_descriptor_path",
    "latest_archive_segment",
    "load_generation_descriptor",
    "select_archive_segment",
    "select_archive_segment_metadata_only",
]
