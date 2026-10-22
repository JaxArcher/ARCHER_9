---
name: Documents & Artifacts
description: Create, edit, and open Word (.docx), PowerPoint (.pptx), Excel (.xlsx), and PDF files in ARCHER's artifacts folder.
category: documents
---

### create_word_document
Create a styled Word document (.docx). Use this when the user asks to write, draft, or export a report, summary, notes, or article as a Word document.
**Parameters:**
- title: The document title (string).
- content: The text or markdown content (string). Supports headings (#, ##), bullet points (-), and numbered lists.
- filename: (optional) The target filename (e.g. 'Meeting_Notes.docx'). Defaults to a timestamped filename in data/artifacts/.

### edit_word_document
Append content to an existing Word document.
**Parameters:**
- filepath: Path or filename of the document to edit (string).
- append_text: Text or bullet points to append to the document (string).
- output_filename: (optional) Filename for the modified copy. If omitted, updates the file.

### create_presentation
Create a 16:9 widescreen PowerPoint deck (.pptx). Use this when the user asks to create a presentation, slides, or slide deck.
**Parameters:**
- title: The presentation title (string).
- subtitle: (optional) The presentation subtitle (string).
- slides: A list of slide objects. Each object has: title (string), bullets (list of strings), and optional notes (string).
- filename: (optional) The target filename (e.g. 'Project_Update.pptx').

### create_spreadsheet
Create an Excel spreadsheet (.xlsx) with styled headers and formulas. Use this when the user asks for a table, budget, schedule, breakdown, or sheet with totals.
**Parameters:**
- title: The workbook or primary sheet title (string).
- sheets: (optional) List of sheet definitions: [{"name": "Expenses", "headers": ["Category", "Amount"], "rows": [["Software", 50]], "total_columns": ["Amount"]}].
- headers: (optional) Column headers if using single-sheet mode (list of strings).
- rows: (optional) Data rows if using single-sheet mode (list of lists).
- total_columns: (optional) Column names that should calculate a sum total at the bottom (list of strings).
- filename: (optional) Target filename (e.g. 'Q4_Budget.xlsx').

### create_pdf
Create a professional PDF document. Use this when the user asks for a PDF summary, memo, or export.
**Parameters:**
- title: The document title (string).
- content: The text or markdown content (string).
- filename: (optional) Target filename (e.g. 'Weekly_Briefing.pdf').

### merge_pdfs
Merge multiple PDF documents into a single PDF.
**Parameters:**
- pdf_files: List of file paths or filenames of the PDFs to merge (list of strings).
- output_filename: (optional) Target filename for the combined PDF.

### open_document
Launch a file natively in Microsoft Word, PowerPoint, Excel, or default PDF viewer. Use this when the user asks to open, view, or launch a document.
**Parameters:**
- filepath: Path or filename of the document to open (string).

### show_in_folder
Open Windows File Explorer with the specified file selected. Use this when the user asks where a file is saved or wants to see it in the folder.
**Parameters:**
- filepath: Path or filename of the document (string).

### list_artifacts
List all files created by ARCHER in the artifacts folder, newest first.
**Parameters:**
- extension: (optional) Filter by file extension without dot (e.g. 'pdf', 'docx', 'pptx', 'xlsx').
