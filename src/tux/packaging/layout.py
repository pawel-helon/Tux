"""Assemble a dpkg-deb-ready package tree."""

import gzip
import shutil
from pathlib import Path

from .constants import BINARY_NAME, CONFIG, COPYRIGHT, POSTRM, TEMPLATES
from .metadata import build_date, changelog, changelog_filename, control_file, package_name
from .scripts import postinst


def lay_out_package(
    dest: Path,
    binary: Path,
    *,
    version: str,
    architecture: str,
    date: str | None = None,
    variant: str | None = None,
) -> Path:
    """Assemble a ``dpkg-deb``-ready tree at ``dest``."""
    debian_dir = dest / "DEBIAN"
    bin_dir = dest / "usr" / "bin"
    doc_dir = dest / "usr" / "share" / "doc" / package_name(variant)
    for directory in (debian_dir, bin_dir, doc_dir):
        directory.mkdir(parents=True, exist_ok=True)

    installed_binary = bin_dir / BINARY_NAME
    shutil.copy2(binary, installed_binary)
    installed_binary.chmod(0o755)

    installed_size = max(1, installed_binary.stat().st_size // 1024)
    _write(
        debian_dir / "control",
        control_file(
            version=version,
            architecture=architecture,
            installed_size=installed_size,
            variant=variant,
        ),
        0o644,
    )
    _write(debian_dir / "templates", TEMPLATES, 0o644)
    _write(debian_dir / "config", CONFIG, 0o755)
    _write(debian_dir / "postinst", postinst(variant), 0o755)
    _write(debian_dir / "postrm", POSTRM, 0o755)

    _write(doc_dir / "copyright", COPYRIGHT, 0o644)
    _write_gz(
        doc_dir / changelog_filename(version),
        changelog(version=version, date=date or build_date(), variant=variant),
        0o644,
    )

    _normalize_dir_perms(dest)
    return dest


def _write(path: Path, content: str, mode: int) -> None:
    """Write UTF-8 content and set its mode."""
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


def _write_gz(path: Path, content: str, mode: int) -> None:
    """Write reproducible maximum-compression gzip content."""
    path.write_bytes(gzip.compress(content.encode("utf-8"), compresslevel=9, mtime=0))
    path.chmod(mode)


def _normalize_dir_perms(dest: Path) -> None:
    """Force every directory in the package tree to 0755."""
    for directory in (dest, *dest.rglob("*")):
        if directory.is_dir():
            directory.chmod(0o755)
