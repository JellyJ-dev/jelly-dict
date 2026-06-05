from __future__ import annotations

import tempfile
from pathlib import Path


def new_temp_path(path: Path) -> Path:
    with tempfile.NamedTemporaryFile(
        delete=False,
        dir=path.parent,
        prefix=f".{path.stem}.",
        suffix=path.suffix,
    ) as temp_file:
        return Path(temp_file.name)
