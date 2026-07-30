"""Render final Markdown into reviewable office-document formats."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Iterable


def _plain_lines(markdown: str) -> list[str]:
    result = []
    for line in markdown.splitlines():
        cleaned = line.lstrip("#").strip()
        if cleaned:
            result.append(cleaned)
    return result


def render_bundle(markdown_path: Path, formats: Iterable[str]) -> list[Path]:
    markdown = markdown_path.read_text(encoding="utf-8")
    requested = set(formats)
    rendered: list[Path] = []
    if "html" in requested:
        target = markdown_path.with_suffix(".html")
        body = "\n".join(f"<p>{html.escape(line)}</p>" for line in _plain_lines(markdown))
        target.write_text(
            "<!doctype html><html lang=\"ko\"><meta charset=\"utf-8\">"
            "<title>AI Office Deliverable</title><body>" + body + "</body></html>",
            encoding="utf-8",
        )
        rendered.append(target)
    if "docx" in requested:
        try:
            from docx import Document
        except ImportError as error:
            raise RuntimeError("DOCX rendering requires python-docx") from error
        document = Document()
        for line in markdown.splitlines():
            if line.startswith("# "):
                document.add_heading(line[2:].strip(), level=1)
            elif line.startswith("## "):
                document.add_heading(line[3:].strip(), level=2)
            elif line.strip():
                document.add_paragraph(line.strip())
        target = markdown_path.with_suffix(".docx")
        document.save(target)
        rendered.append(target)
    if "pdf" in requested:
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.cidfonts import UnicodeCIDFont
            from reportlab.pdfgen.canvas import Canvas
        except ImportError as error:
            raise RuntimeError("PDF rendering requires reportlab") from error
        target = markdown_path.with_suffix(".pdf")
        font_name = "HYSMyeongJo-Medium"
        pdfmetrics.registerFont(UnicodeCIDFont(font_name))
        canvas = Canvas(str(target), pagesize=A4)
        width, height = A4
        canvas.setFont(font_name, 10)
        y = height - 50
        for line in _plain_lines(markdown):
            for offset in range(0, max(1, len(line)), 90):
                canvas.drawString(45, y, line[offset : offset + 90])
                y -= 15
                if y < 45:
                    canvas.showPage()
                    canvas.setFont(font_name, 10)
                    y = height - 50
        canvas.save()
        rendered.append(target)
    if "xlsx" in requested:
        try:
            from openpyxl import Workbook
        except ImportError as error:
            raise RuntimeError("XLSX rendering requires openpyxl") from error
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Deliverable"
        sheet.append(["Line", "Content"])
        for index, line in enumerate(_plain_lines(markdown), start=1):
            sheet.append([index, line])
        target = markdown_path.with_suffix(".xlsx")
        workbook.save(target)
        rendered.append(target)
    manifest = markdown_path.with_name("ARTIFACTS.json")
    manifest.write_text(
        json.dumps(
            {
                "source": markdown_path.name,
                "rendered": [path.name for path in rendered],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    rendered.append(manifest)
    return rendered
