from __future__ import annotations

from pathlib import Path

from app.core.domain import ExportSourceRow, ExportSourceSnapshot
from app.storage.excel_repository import WorkbookRepository


class OpenpyxlExportSource:
    def __init__(self, repository: WorkbookRepository | None = None) -> None:
        self._repository = repository or WorkbookRepository()

    def read_rows(self, path: Path, language: str) -> list[ExportSourceRow]:
        return list(self.prepare_snapshot(path, language).rows)

    def prepare_snapshot(
        self,
        path: Path,
        language: str,
    ) -> ExportSourceSnapshot:
        snapshot = self._repository.read_snapshot(path)
        output: list[ExportSourceRow] = []
        for row in snapshot.rows:
            data = {cell.key: cell.value if cell.value is not None else "" for cell in row.cells}
            row_language = str(data.get("language", "") or "").strip()
            if data.get("word") and row_language == language:
                output.append(ExportSourceRow(row.ref, data))
        return ExportSourceSnapshot(
            path=snapshot.path,
            revision=snapshot.revision,
            rows=tuple(output),
        )
