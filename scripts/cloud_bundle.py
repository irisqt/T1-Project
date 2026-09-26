"""Build a deployment archive from a strict code allowlist; never walk reference folders."""
from __future__ import annotations
import argparse
import hashlib
import gzip
import io
import json
from pathlib import Path
import tarfile
import tomllib

ALLOWED_TREES = {"src/bitget_bot": {".py"}, "infra/gcp": {".py", ".sh", ".service", ".timer"}}
REQUIRED = ("src/bitget_bot/__main__.py", "config/paper.toml", "infra/gcp/install.sh")
EXCLUDED_PARTS = {".git", ".env", ".venv", "__pycache__", "data", "secrets", "artifacts"}

def source_files(root: Path) -> list[Path]:
    root = root.resolve(strict=True)
    result = []
    for relative, suffixes in ALLOWED_TREES.items():
        tree = root / relative
        if tree.is_symlink() or not tree.is_dir():
            raise ValueError(f"Expected a real source directory: {relative}")
        for path in tree.rglob("*"):
            rel = path.relative_to(root)
            if any(p in EXCLUDED_PARTS or p.startswith(".env") for p in rel.parts):
                continue
            if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root):
                raise ValueError(f"Symbolic link is forbidden: {rel}")
            if path.is_file() and path.suffix in suffixes:
                if path.resolve().is_relative_to(root):
                    result.append(path)
                else:
                    raise ValueError(f"Source escapes project root: {rel}")
    config = root / "config/paper.toml"
    if config.is_symlink() or config.parent.is_symlink():
        raise ValueError("Paper configuration must not be a symbolic link")
    result.append(config)
    for required in REQUIRED:
        if root / required not in result or not (root / required).is_file():
            raise ValueError(f"Missing required deployment file: {required}")
    with config.open("rb") as handle:
        settings = tomllib.load(handle)
    mode = settings.get("mode", settings.get("app", {}).get("mode", settings.get("trading", {}).get("mode")))
    if mode != "paper":
        raise ValueError("Cloud bundle accepts paper mode only")
    return sorted(set(result))

def build(root: Path, output: Path) -> dict:
    root = root.resolve(strict=True)
    paths = source_files(root)
    output = output.resolve()
    if not output.is_relative_to(root / "artifacts"):
        raise ValueError("Deployment archive must be under this project's artifacts directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    records = []
    with output.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed, tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for path in paths:
            relative = path.relative_to(root).as_posix()
            content = path.read_bytes()
            # Deployment shell/unit sources use Unix line endings regardless of Windows checkout.
            if path.suffix in {".sh", ".service", ".timer"}:
                content = content.replace(b"\r\n", b"\n")
            info = tarfile.TarInfo(relative)
            info.size = len(content)
            info.mode = 0o755 if path.suffix == ".sh" else 0o644
            info.mtime = 0
            archive.addfile(info, io.BytesIO(content))
            records.append({"path": relative, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)})
        manifest = {"format": 1, "mode": "paper", "files": records}
        payload = (json.dumps(manifest, indent=2) + "\n").encode()
        info = tarfile.TarInfo("BUILD_MANIFEST.json")
        info.mode = 0o644
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum = output.with_suffix(output.suffix + ".sha256")
    checksum.write_text(f"{digest}  {output.name}\n", encoding="ascii")
    return {"archive": str(output), "sha256": digest, "files": len(records), "mode": "paper"}

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = build(args.root, args.output or args.root / "artifacts/cloud/bitget-paper.tar.gz")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
