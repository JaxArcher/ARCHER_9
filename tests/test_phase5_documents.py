"""
Unit and integration tests for Phase 5 Documents & Artifacts (Spec Section 8).
"""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from archer.core.approvals import get_approval_manager
from archer.tools.document_tools import DocumentTools
from archer.skills.tool_executor import UniversalToolExecutor


@pytest.fixture(scope="module")
def doc_tools():
    return DocumentTools()


def test_create_word_document(doc_tools):
    """Test Word document creation via DocumentTools in isolated env."""
    filename = "Test_Phase5_Word.docx"
    content = (
        "# Executive Summary\n"
        "ARCHER Phase 5 provides full document authoring.\n\n"
        "## Key Deliverables\n"
        "- Word .docx generation and editing\n"
        "- PowerPoint .pptx widescreen decks\n"
        "- Excel .xlsx workbooks with formulas\n"
        "- PDF .pdf report compilation and merging\n"
    )
    result = doc_tools.create_word_document(
        title="ARCHER Phase 5 Status Report",
        content=content,
        filename=filename,
    )

    assert result.get("status") == "success", f"Failed: {result}"
    out_file = Path(result["filepath"])
    assert out_file.exists(), f"File does not exist: {out_file}"
    assert out_file.stat().st_size > 500, "Generated Word doc is unexpectedly small"


def test_edit_word_document(doc_tools):
    """Test appending content to an existing Word document."""
    base_file = "Test_Phase5_Word.docx"
    append_text = (
        "\n## Additional Notes\n"
        "- Section appended during test verification.\n"
    )
    result = doc_tools.edit_word_document(
        filepath=base_file,
        append_text=append_text,
        output_filename="Test_Phase5_Word_Edited.docx",
    )

    assert result.get("status") == "success", f"Failed: {result}"
    out_file = Path(result["filepath"])
    assert out_file.exists()
    assert out_file.stat().st_size > 500


def test_create_presentation(doc_tools):
    """Test 16:9 widescreen PowerPoint creation."""
    filename = "Test_Phase5_Deck.pptx"
    slides = [
        {
            "title": "Architecture Overview",
            "bullets": [
                "Local Python environment isolation (envs/document_tools)",
                "Standard IPC payload execution",
                "Direct native app integration on Windows host",
            ],
            "notes": "Speaker notes for slide 1.",
        },
        {
            "title": "Supported Formats",
            "bullets": [
                "Word (.docx) with markdown formatting",
                "PowerPoint (.pptx) widescreen slides",
                "Excel (.xlsx) with styled headers and formulas",
                "PDF (.pdf) with ReportLab and PyPDF",
            ],
            "notes": "Speaker notes for slide 2.",
        },
    ]

    result = doc_tools.create_presentation(
        title="ARCHER Workspace Capabilities",
        subtitle="Spec Section 8 Implementation",
        slides=slides,
        filename=filename,
    )

    assert result.get("status") == "success", f"Failed: {result}"
    out_file = Path(result["filepath"])
    assert out_file.exists()
    assert out_file.stat().st_size > 1000


def test_create_spreadsheet(doc_tools):
    """Test Excel creation with styled headers and SUM formula calculation."""
    filename = "Test_Phase5_Budget.xlsx"
    headers = ["Category", "Quantity", "Unit Cost", "Subtotal"]
    rows = [
        ["Compute Nodes", 2, 850.00, "=B2*C2"],
        ["SSD Storage", 4, 120.00, "=B3*C3"],
        ["Network Switch", 1, 350.00, "=B4*C4"],
    ]
    total_columns = ["Subtotal"]

    result = doc_tools.create_spreadsheet(
        title="Hardware Upgrades Q4",
        headers=headers,
        rows=rows,
        total_columns=total_columns,
        filename=filename,
    )

    assert result.get("status") == "success", f"Failed: {result}"
    out_file = Path(result["filepath"])
    assert out_file.exists()
    assert out_file.stat().st_size > 1000


def test_create_pdf_and_merge(doc_tools):
    """Test PDF generation via ReportLab and merging via PyPDF."""
    pdf1 = "Test_Phase5_Part1.pdf"
    pdf2 = "Test_Phase5_Part2.pdf"
    merged = "Test_Phase5_Merged.pdf"

    res1 = doc_tools.create_pdf(
        title="Document Part One",
        content="This is the first segment of the report.",
        filename=pdf1,
    )
    assert res1.get("status") == "success"

    res2 = doc_tools.create_pdf(
        title="Document Part Two",
        content="This is the concluding segment of the report.",
        filename=pdf2,
    )
    assert res2.get("status") == "success"

    merge_res = doc_tools.merge_pdfs(
        pdf_files=[pdf1, pdf2],
        output_filename=merged,
    )
    assert merge_res.get("status") == "success"
    merged_file = Path(merge_res["filepath"])
    assert merged_file.exists()
    assert merged_file.stat().st_size > 1000


def test_list_artifacts(doc_tools):
    """Test listing artifacts in data/artifacts/."""
    all_files = doc_tools.list_artifacts()
    assert len(all_files) > 0, "Expected at least one artifact in data/artifacts/"

    names = [f["name"] for f in all_files]
    assert "Test_Phase5_Word.docx" in names
    assert "Test_Phase5_Deck.pptx" in names

    # Extension filter test
    docx_files = doc_tools.list_artifacts(extension="docx")
    assert all(f["extension"] == "docx" for f in docx_files)


def test_open_and_show_in_folder_mock(doc_tools):
    """Test native open and show in folder functions with mocked OS calls."""
    test_file = "Test_Phase5_Word.docx"

    with patch("os.startfile") as mock_startfile:
        res = doc_tools.open_document(test_file)
        assert res.get("status") == "success"
        mock_startfile.assert_called_once()

    with patch("subprocess.run") as mock_run:
        res = doc_tools.show_in_folder(test_file)
        assert res.get("status") == "success"
        mock_run.assert_called_once()

    # Non-existent file should report clean error
    missing_res = doc_tools.open_document("definitely_nonexistent_file_xyz.docx")
    assert "error" in missing_res


def test_approval_gating_for_documents():
    """Verify document tools classification in ApprovalManager."""
    mgr = get_approval_manager()

    read_only = ["open_document", "show_in_folder", "list_artifacts"]
    for t in read_only:
        needs_appr, reason = mgr.should_gate(t, {})
        assert not needs_appr, f"{t} should not gate"
        assert reason == "read_only"

    self_record = [
        "create_word_document",
        "create_presentation",
        "create_spreadsheet",
        "create_pdf",
        "merge_pdfs",
    ]
    for t in self_record:
        needs_appr, reason = mgr.should_gate(t, {})
        assert not needs_appr, f"{t} should self-record"
        assert reason == "self_record"

    # Editing existing documents modifies files and must gate unless session-approved (Spec Section 8)
    needs_appr, reason = mgr.should_gate("edit_word_document", {"filepath": "doc.docx"})
    assert needs_appr, "edit_word_document should require approval"
    assert reason == "changes_state"

    # Under session approval, edit_word_document is allowed
    mgr.session_approval_active = True
    needs_appr, reason = mgr.should_gate("edit_word_document", {"filepath": "doc.docx"})
    assert not needs_appr, "edit_word_document should be permitted under session approval"
    assert reason == "session_approved"
    mgr.session_approval_active = False


def test_universal_tool_executor_documents_routing():
    """Verify UniversalToolExecutor routes documents skill category calls."""
    executor = UniversalToolExecutor()

    # Execute list_artifacts
    res = executor.execute("list_artifacts", {})
    assert "result" in res or "error" not in res
    assert isinstance(res.get("result"), list)

    # Execute create_word_document
    doc_res = executor.execute("create_word_document", {
        "title": "Executor Integration Test",
        "content": "Testing executor routing for documents category.",
        "filename": "Test_Executor_Word.docx",
    })
    assert doc_res.get("status") == "success"
    assert Path(doc_res["filepath"]).exists()
