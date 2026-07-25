"""Resume parser — extract text from PDF / DOCX / TXT files."""

from __future__ import annotations

import io
from pathlib import Path


async def parse_resume(file_bytes: bytes, filename: str) -> str:
    """Extract text from a resume file. Supports PDF, DOCX, TXT.

    Returns the extracted text (truncated to 3000 chars for LLM context).
    """
    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        text = _parse_pdf(file_bytes)
    elif ext in (".docx", ".doc"):
        text = _parse_docx(file_bytes)
    elif ext == ".txt":
        text = file_bytes.decode("utf-8", errors="replace")
    else:
        raise ValueError(f"不支持的文件格式: {ext}，请上传 PDF、DOCX 或 TXT 文件。")

    # Truncate for LLM context
    return text[:3000]


# ── PDF ──────────────────────────────────────────────────

def _parse_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF bytes."""
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        raise ImportError("PDF 解析需要 PyPDF2。请运行: pip install PyPDF2")

    reader = PdfReader(io.BytesIO(file_bytes))
    lines = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            lines.append(text)
    return "\n".join(lines)


# ── DOCX ─────────────────────────────────────────────────

def _parse_docx(file_bytes: bytes) -> str:
    """Extract text from DOCX bytes."""
    try:
        from docx import Document
    except ImportError:
        raise ImportError("DOCX 解析需要 python-docx。请运行: pip install python-docx")

    doc = Document(io.BytesIO(file_bytes))
    lines = [para.text for para in doc.paragraphs if para.text.strip()]
    return "\n".join(lines)
