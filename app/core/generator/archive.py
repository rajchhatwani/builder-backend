"""Pure helpers around a generated FileTree: manifest and a deterministic zip."""

import hashlib
import io
import zipfile
from typing import Any

from app.core.generator.base import FileTree

# Fixed timestamp and permissions so the same files always give byte-identical zips.
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
_FILE_MODE = 0o644 << 16


def manifest(files: FileTree) -> list[dict[str, Any]]:
    return [
        {
            "path": path,
            "size": len(content.encode("utf-8")),
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }
        for path, content in sorted(files.items())
    ]


def build_zip(root: str, files: FileTree) -> bytes:
    """Zip every file under `<root>/`. `root` must be a validated slug."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in sorted(files.items()):
            info = zipfile.ZipInfo(f"{root}/{path}", date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = _FILE_MODE
            archive.writestr(info, content.encode("utf-8"))
    return buffer.getvalue()
