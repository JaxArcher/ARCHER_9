"""
ARCHER Document Tools (Phase 5, Spec Section 8).

Provides creation, modification, native opening, and artifact listing for:
- Word (.docx) via python-docx
- PowerPoint (.pptx) via python-pptx
- Excel (.xlsx) via openpyxl
- PDF (.pdf) via reportlab and pypdf

All heavy generation runs isolated in envs/document_tools (Spec Section 8).
Files are placed in data/artifacts/ by default.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from archer.core.event_bus import Event, EventType, get_event_bus


class DocumentTools:
    """Manages creation, editing, and native launching of documents."""

    def __init__(self) -> None:
        self._bus = get_event_bus()
        self._repo_root = Path(__file__).resolve().parents[3]
        self._artifacts_dir = self._repo_root / "data" / "artifacts"
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)

        self._doc_env_python = self._repo_root / "envs" / "document_tools" / "Scripts" / "python.exe"
        self._worker_script = Path(__file__).parent / "document_worker.py"

    def _resolve_output_path(self, filename: Optional[str], default_ext: str) -> Path:
        """Resolve a filename or path into the data/artifacts directory."""
        if not filename or not filename.strip():
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"Document_{ts}.{default_ext}"

        p = Path(filename.strip())
        if not p.suffix:
            p = p.with_suffix(f".{default_ext}")

        if not p.is_absolute():
            p = self._artifacts_dir / p.name

        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _run_worker(self, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute action via document_worker.py inside envs/document_tools environment."""
        if not self._doc_env_python.exists():
            return {
                "error": f"Document tools environment not found at {self._doc_env_python}. Run setup first."
            }

        payload = {"action": action, "data": data}
        try:
            res = subprocess.run(
                [str(self._doc_env_python), str(self._worker_script)],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if res.returncode != 0:
                logger.error(f"[DocumentTools] Worker failed ({res.returncode}): {res.stderr}")
                return {"error": f"Document worker error: {res.stderr.strip()}"}

            out = json.loads(res.stdout.strip())
            if out.get("status") == "success":
                # Notify event bus of new artifact
                self._bus.publish(Event(
                    type=EventType.ARTIFACT_DISPLAY,
                    source="document_tools",
                    data={
                        "filename": out.get("filename"),
                        "filepath": out.get("filepath"),
                        "action": action,
                    }
                ))
            return out
        except subprocess.TimeoutExpired:
            return {"error": "Document generation timed out after 60s."}
        except Exception as e:
            logger.error(f"[DocumentTools] Worker call error: {e}")
            return {"error": str(e)}

    # --- Tool Implementations ---

    def create_word_document(
        self, title: str, content: str, filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a styled Word document (.docx)."""
        out_path = self._resolve_output_path(filename, "docx")
        return self._run_worker("create_word", {
            "title": title,
            "content": content,
            "output_path": str(out_path),
        })

    def edit_word_document(
        self, filepath: str, append_text: str, output_filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """Append sections to an existing Word document."""
        p_in = Path(filepath)
        if not p_in.is_absolute():
            p_in = self._artifacts_dir / p_in
        if not p_in.exists():
            return {"error": f"File not found: {p_in}"}

        out_path = self._resolve_output_path(output_filename or p_in.name, "docx")
        return self._run_worker("edit_word", {
            "filepath": str(p_in),
            "append_text": append_text,
            "output_path": str(out_path),
        })

    def create_presentation(
        self,
        title: str,
        subtitle: Optional[str] = None,
        slides: Optional[List[Dict[str, Any]]] = None,
        filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a 16:9 widescreen presentation (.pptx)."""
        out_path = self._resolve_output_path(filename, "pptx")
        return self._run_worker("create_presentation", {
            "title": title,
            "subtitle": subtitle or "",
            "slides": slides or [],
            "output_path": str(out_path),
        })

    def create_spreadsheet(
        self,
        title: str,
        sheets: Optional[List[Dict[str, Any]]] = None,
        headers: Optional[List[str]] = None,
        rows: Optional[List[List[Any]]] = None,
        total_columns: Optional[List[str]] = None,
        filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a formatted Excel spreadsheet (.xlsx) with totals and formulas."""
        out_path = self._resolve_output_path(filename, "xlsx")
        return self._run_worker("create_spreadsheet", {
            "title": title,
            "sheets": sheets or [],
            "headers": headers or [],
            "rows": rows or [],
            "total_columns": total_columns or [],
            "output_path": str(out_path),
        })

    def create_pdf(
        self, title: str, content: str, filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a styled PDF document (.pdf)."""
        out_path = self._resolve_output_path(filename, "pdf")
        return self._run_worker("create_pdf", {
            "title": title,
            "content": content,
            "output_path": str(out_path),
        })

    def merge_pdfs(
        self, pdf_files: List[str], output_filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """Merge multiple PDF files into one."""
        resolved_files = []
        for f in pdf_files:
            p = Path(f)
            if not p.is_absolute():
                p = self._artifacts_dir / p
            resolved_files.append(str(p))

        out_path = self._resolve_output_path(output_filename, "pdf")
        return self._run_worker("merge_pdfs", {
            "pdf_files": resolved_files,
            "output_path": str(out_path),
        })

    def open_document(self, filepath: str) -> Dict[str, Any]:
        """Open a file natively in Microsoft Word, PowerPoint, Excel, or PDF reader."""
        p = Path(filepath)
        if not p.is_absolute():
            p = self._artifacts_dir / p
        if not p.exists():
            return {"error": f"File not found: {p}"}

        try:
            os.startfile(str(p))
            return {"status": "success", "message": f"Opened {p.name} in native application."}
        except Exception as e:
            logger.error(f"[DocumentTools] Failed opening document {p}: {e}")
            return {"error": f"Failed to open document: {e}"}

    def show_in_folder(self, filepath: str) -> Dict[str, Any]:
        """Open Windows Explorer with the specified file selected."""
        p = Path(filepath)
        if not p.is_absolute():
            p = self._artifacts_dir / p
        if not p.exists():
            return {"error": f"File not found: {p}"}

        try:
            subprocess.run(["explorer.exe", f"/select,{str(p)}"], check=False)
            return {"status": "success", "message": f"Showed {p.name} in Explorer."}
        except Exception as e:
            return {"error": f"Failed to show in folder: {e}"}

    def list_artifacts(self, extension: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all files in data/artifacts/, newest first."""
        if not self._artifacts_dir.exists():
            return []

        files = []
        ext_filter = f".{extension.lstrip('.')}".lower() if extension else None

        for p in self._artifacts_dir.iterdir():
            if not p.is_file():
                continue
            if ext_filter and p.suffix.lower() != ext_filter:
                continue

            stat = p.stat()
            mtime = datetime.datetime.fromtimestamp(stat.st_mtime)
            files.append({
                "name": p.name,
                "path": str(p.resolve()),
                "extension": p.suffix.lstrip(".").lower(),
                "size_bytes": stat.st_size,
                "modified_at": mtime.strftime("%Y-%m-%d %H:%M:%S"),
                "modified_iso": mtime.isoformat(),
            })

        files.sort(key=lambda x: x["modified_at"], reverse=True)
        return files
