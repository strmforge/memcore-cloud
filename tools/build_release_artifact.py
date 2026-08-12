#!/usr/bin/env python3
"""Build a Time Library release zip and checksum.

Use `--source head` for an immutable release artifact. Use
`--source working-tree` only for pre-commit smoke tests; it packages tracked
edits plus untracked non-ignored files without copying local runtime data.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "release"
EXCLUDED_TOP_LEVEL_FILES = {
    ".checkpoint",
    ".checkpoint_p2.json",
    "AGENTS.md",
    "CODEX_CONTINUITY_LEDGER.md",
    "design-qa.md",
    "known-issues.md",
    "raw",
    "update_history.jsonl",
}
EXCLUDED_RELATIVE_PATHS = {
    "benchmarks/README.md",
    "docs/2026-07-02-checkpoint-remaining-risk-inventory.md",
    "config/private_release_denylist.local.txt",
    "config/window_binding_registry.json",
    "docs/github-positioning-2026.6.16.md",
    "src/codex_memory_judge.py",
    "src/eval_entrypoints.py",
    "src/eval_miss_report.py",
    "src/eval_resource_ledger.py",
    "src/free_memory_benchmark.py",
    "src/model_matrix_compare.py",
    "src/model_memory_judge.py",
    "src/official_memory_benchmarks.py",
    "tools/codex_memory_judge.py",
    "tools/code_change_tiandao_audit.py",
    "tools/core_record_multi_host_audit.py",
    "tools/eval_miss_report.py",
    "tools/eval_run_compare.py",
    "tools/free_memory_benchmark.py",
    "tools/memcore_eval_entry.py",
    "tools/model_heavy_qa_runner.py",
    "tools/model_matrix_compare.py",
    "tools/model_matrix_eval.py",
    "tools/model_memory_judge.py",
    "tools/official_memory_benchmark.py",
    "tools/r730_eval_stage_sync.sh",
    "tools/time_twin_star_installed_runtime_probe.py",
    "tools/time_twin_star_passive_push_trace_gate.py",
    "tools/time_twin_star_turn_loop_probe.py",
    "tools/time_twin_star_turn_loop_trace_gate.py",
}
PACKAGED_TOOL_FILES = {
    "build_fts5_recall_index.py",
    "claude_code_preflight_hook.py",
    "claude_desktop_mcp_bridge.py",
    "configure_codex_mcp_policy.py",
    "codex_mcp_config_guard.py",
    "codex_mcp_bridge.py",
    "distill_transparency.py",
    "hermes_autonomous_loop.py",
    "install_claude_code_preflight_hook.py",
    "install_claude_desktop_skill.py",
    "install_config_merge.py",
    "install_runtime_identity.py",
    "install_runtime_quiescence.py",
    "install_state_migrate.py",
    "install_transaction_snapshot.py",
    "linux_full_install.sh",
    "macos_full_install.sh",
    "macos_menu_bar.swift",
    "prepare_granite_vector_assets.py",
    "refresh_claude_desktop_mcp_bridges.py",
    "runtime_profile.py",
    "windows_double_click_install.ps1",
    "windows_full_install.ps1",
    "windows_guardian.ps1",
    "windows_hidden_guardian.vbs",
    "windows_native_smoke.ps1",
    "windows_tray.ps1",
}
EXCLUDED_PATH_PARTS = {
    ".git",
    ".playwright-cli",
    ".release-gate-venv",
    ".venv",
    ".pytest_cache",
    "__pycache__",
    "backups",
    "experience_lancedb",
    "input",
    "logs",
    "memory",
    "output",
    "release",
    "runtime",
    "tests",
    "update_staging",
    "zhiyi",
}
EXCLUDED_RELATIVE_PREFIXES = (
    "benchmarks/cache/",
    "benchmarks/eval-runs/",
    "benchmarks/results/",
    "docs/construction/",
    "docs/decisions/",
    "docs/fixtures/",
    "docs/internal/",
    "docs/releases/",
    "system/skills/" + "yifan" + "chen" + "-zhiyi" + "/",
)


def _capture(cmd: list[str], *, cwd: Path = ROOT) -> str:
    return subprocess.check_output(cmd, cwd=str(cwd), text=True).strip()


def _run(cmd: list[str], *, cwd: Path = ROOT) -> None:
    print(f"[release-artifact] $ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=str(cwd), check=True)


def _version(root: Path = ROOT) -> str:
    version_path = root / "VERSION"
    if not version_path.exists():
        raise FileNotFoundError("VERSION file is missing")
    version = version_path.read_text(encoding="utf-8").strip()
    if not version:
        raise ValueError("VERSION file is empty")
    return version


def _copy_git_head(source_dir: Path) -> None:
    archive = source_dir.parent / "head.tar"
    _run(["git", "archive", "--format=tar", "-o", str(archive), "HEAD"])
    source_dir.mkdir(parents=True, exist_ok=True)
    _run(["tar", "-xf", str(archive), "-C", str(source_dir)])


def _git_working_tree_files(root: Path = ROOT) -> list[Path]:
    output = _capture(["git", "ls-files", "--cached", "--modified", "--others", "--exclude-standard"], cwd=root)
    files: list[Path] = []
    for line in output.splitlines():
        rel = line.strip()
        if not rel:
            continue
        path = root / rel
        if path.is_file():
            files.append(Path(rel))
    return sorted(set(files), key=lambda p: p.as_posix())


def _snapshot_files(root: Path = ROOT) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _should_package(rel):
            files.append(rel)
    return sorted(set(files), key=lambda p: p.as_posix())


def _should_package(rel: Path) -> bool:
    rel_posix = rel.as_posix()
    if rel_posix in EXCLUDED_TOP_LEVEL_FILES or rel_posix in EXCLUDED_RELATIVE_PATHS:
        return False
    if any(rel_posix.startswith(prefix) for prefix in EXCLUDED_RELATIVE_PREFIXES):
        return False
    if rel.parts[:1] == ("tools",):
        return len(rel.parts) == 2 and rel.parts[1] in PACKAGED_TOOL_FILES
    return not any(part in EXCLUDED_PATH_PARTS for part in rel.parts)


def _copy_working_tree(source_dir: Path, *, root: Path = ROOT) -> None:
    source_dir.mkdir(parents=True, exist_ok=True)
    file_list = _git_working_tree_files(root) if (root / ".git").exists() else _snapshot_files(root)
    for rel in file_list:
        if not _should_package(rel):
            continue
        src = root / rel
        dst = source_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_zip(source_dir: Path, output_zip: Path, prefix: str) -> None:
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    if output_zip.exists():
        output_zip.unlink()
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(source_dir).as_posix()
            if not _should_package(Path(rel)):
                continue
            archive.write(path, f"{prefix}/{rel}")


def build_artifact(*, source: str, output_dir: Path, keep_temp: bool = False) -> dict[str, str]:
    version = _version(ROOT)
    prefix = f"time-library-{version}"
    tmp = Path(tempfile.mkdtemp(prefix="time-library-release-artifact-"))
    source_dir = tmp / "source"
    try:
        if source == "head":
            _copy_git_head(source_dir)
        elif source == "working-tree":
            _copy_working_tree(source_dir, root=ROOT)
        else:
            raise ValueError(f"unsupported source: {source}")

        output_zip = output_dir / f"{prefix}.zip"
        _write_zip(source_dir, output_zip, prefix)
        checksum = _sha256(output_zip)
        checksum_path = output_dir / f"{output_zip.name}.sha256"
        checksum_path.write_text(f"{checksum}  {output_zip.name}\n", encoding="ascii")
        return {
            "version": version,
            "source": source,
            "zip": str(output_zip),
            "sha256": str(checksum_path),
            "checksum": checksum,
            "size_bytes": str(output_zip.stat().st_size),
        }
    finally:
        if keep_temp:
            print(f"[release-artifact] kept temp dir: {tmp}", flush=True)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Time Library release zip and sha256.")
    parser.add_argument("--source", choices=("head", "working-tree"), default="head")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args()

    result = build_artifact(source=args.source, output_dir=Path(args.output_dir), keep_temp=args.keep_temp)
    print(f"[release-artifact] built {result['zip']}", flush=True)
    print(f"[release-artifact] sha256 {result['checksum']}", flush=True)
    print(f"[release-artifact] checksum-file {result['sha256']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
