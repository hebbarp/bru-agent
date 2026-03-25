"""
PDF Generator Skill - Creates PDF documents from content.

Supports (in priority order):
1. Typst (fastest, modern typesetting with great styling)
2. Pandoc → LaTeX → PDF (fallback for complex markdown)
3. ReportLab (fallback if above not available)
4. Basic PDF (minimal fallback)
"""

import os
import subprocess
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from loguru import logger

from ..base import BaseSkill

# Check for available tools
PANDOC_AVAILABLE = shutil.which('pandoc') is not None
PDFLATEX_AVAILABLE = shutil.which('pdflatex') is not None

# Hardcoded Typst path (winget install location)
TYPST_HARDCODED_PATH = r'C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Typst.Typst_Microsoft.Winget.Source_8wekyb3d8bbwe\typst-x86_64-pc-windows-msvc\typst.exe'

def get_typst_path():
    """Get typst executable path, checking multiple locations at runtime."""
    # Check hardcoded path first (most reliable after winget install)
    if Path(TYPST_HARDCODED_PATH).exists():
        return TYPST_HARDCODED_PATH
    # Then check PATH
    which_path = shutil.which('typst')
    if which_path:
        return which_path
    return None

# Try to import PDF libraries
try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

logger.info(f"PDF generators available - Typst: {get_typst_path() is not None}, Pandoc: {PANDOC_AVAILABLE}, pdflatex: {PDFLATEX_AVAILABLE}, ReportLab: {REPORTLAB_AVAILABLE}")


class PDFGeneratorSkill(BaseSkill):
    """Skill for generating PDF documents."""

    name = "create_pdf"
    description = "Create a PDF document from text or markdown content. Properly renders markdown formatting (headers, bold, lists, code blocks, etc.). Uses Typst (preferred), Pandoc+LaTeX, or ReportLab for high-quality styled output."
    version = "2.1.0"

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.output_dir = Path(config.get('output_dir', './output')) if config else Path('./output')
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Title of the PDF document"
                },
                "content": {
                    "type": "string",
                    "description": "Main content/body of the PDF. Supports full Markdown formatting (headers, bold, italic, lists, code blocks, tables, etc.)"
                },
                "filename": {
                    "type": "string",
                    "description": "Optional filename for the PDF (without .pdf extension). If not provided, will be generated from title."
                },
                "author": {
                    "type": "string",
                    "description": "Optional author name to include in the PDF"
                },
                "format": {
                    "type": "string",
                    "enum": ["auto", "markdown", "plain"],
                    "description": "Content format: 'auto' (detect), 'markdown', or 'plain' text. Default is 'auto'."
                }
            },
            "required": ["title", "content"]
        }

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a PDF document."""
        title = params.get('title', 'Untitled Document')
        content = params.get('content', '')
        filename = params.get('filename', '')
        author = params.get('author', 'BRU Agent')
        content_format = params.get('format', 'auto')

        if not content:
            return {"success": False, "error": "No content provided for PDF"}

        # Generate filename if not provided
        if not filename:
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
            safe_title = safe_title.replace(' ', '_')[:50]
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{safe_title}_{timestamp}"

        pdf_filename = f"{filename}.pdf"
        filepath = self.output_dir / pdf_filename

        # Detect if content is markdown
        is_markdown = self._is_markdown(content) if content_format == 'auto' else content_format == 'markdown'

        try:
            method_used = "unknown"

            # Method 1: Typst (fastest, modern, great for styled documents)
            typst_path = get_typst_path()
            if typst_path:
                self._create_pdf_typst(filepath, title, content, author)
                method_used = "typst"

            # Method 2: Pandoc + pdflatex (best for complex markdown)
            elif is_markdown and PANDOC_AVAILABLE and PDFLATEX_AVAILABLE:
                self._create_pdf_pandoc(filepath, title, content, author)
                method_used = "pandoc+pdflatex"

            # Method 3: ReportLab (good fallback)
            elif REPORTLAB_AVAILABLE:
                self._create_pdf_reportlab(filepath, title, content, author, is_markdown)
                method_used = "reportlab"

            # Method 4: Basic PDF (minimal fallback)
            else:
                self._create_pdf_simple(filepath, title, content, author)
                method_used = "basic"

            logger.info(f"PDF created using {method_used}: {filepath}")

            return {
                "success": True,
                "result": {
                    "message": f"PDF document '{title}' created successfully",
                    "filename": pdf_filename,
                    "filepath": str(filepath),
                    "size_bytes": filepath.stat().st_size,
                    "method": method_used,
                    "markdown_detected": is_markdown
                }
            }

        except Exception as e:
            logger.error(f"Failed to create PDF: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": f"Failed to create PDF: {str(e)}"}

    def _is_markdown(self, content: str) -> bool:
        """Detect if content contains markdown formatting."""
        markdown_indicators = [
            '# ',      # Headers
            '## ',
            '### ',
            '**',      # Bold
            '__',
            '*',       # Italic (single)
            '_',
            '```',     # Code blocks
            '`',       # Inline code
            '- ',      # Unordered lists
            '* ',
            '1. ',     # Ordered lists
            '> ',      # Blockquotes
            '[',       # Links
            '![',      # Images
            '|',       # Tables
        ]

        for indicator in markdown_indicators:
            if indicator in content:
                return True
        return False

    def _create_pdf_typst(self, filepath: Path, title: str, content: str, author: str):
        """Create PDF using Typst - modern, fast typesetting with great styling support."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Convert markdown to Typst markup
            typst_content = self._markdown_to_typst(content)

            # Create Typst document with styling
            typ_file = tmpdir / "document.typ"
            typst_source = f'''// Document styling
#set document(title: "{title}", author: "{author}")
#set page(
  paper: "us-letter",
  margin: (x: 1in, y: 1in),
  header: align(right, text(size: 9pt, fill: gray)[{title}]),
  footer: align(center, text(size: 9pt, fill: gray)[Page #counter(page).display()])
)
#set text(font: "Linux Libertine", size: 11pt)
#set par(justify: true, leading: 0.65em)
#set heading(numbering: none)
#show heading.where(level: 1): it => block(
  fill: rgb("#f0f0f0"),
  inset: 10pt,
  radius: 4pt,
  width: 100%,
  text(weight: "bold", size: 16pt, it.body)
)
#show heading.where(level: 2): it => text(weight: "bold", size: 14pt, fill: rgb("#333333"), it.body)
#show heading.where(level: 3): it => text(weight: "bold", size: 12pt, fill: rgb("#555555"), it.body)
#show raw: set text(font: "Fira Code", size: 9pt)
#show raw.where(block: true): block.with(
  fill: rgb("#f5f5f5"),
  inset: 10pt,
  radius: 4pt,
  width: 100%,
)
#show link: underline

// Title block
#align(center)[
  #text(size: 24pt, weight: "bold")[{title}]
  #v(0.5em)
  #text(size: 10pt, fill: gray)[By {author} • {datetime.now().strftime('%Y-%m-%d')}]
]
#v(1em)

// Content
{typst_content}
'''
            typ_file.write_text(typst_source, encoding='utf-8')

            # Run typst compile
            output_pdf = tmpdir / "output.pdf"
            typst_exe = get_typst_path()

            result = subprocess.run(
                [typst_exe, 'compile', str(typ_file), str(output_pdf)],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                logger.error(f"Typst error: {result.stderr}")
                raise Exception(f"Typst failed: {result.stderr}")

            # Copy to final destination
            shutil.copy(output_pdf, filepath)

            logger.info(f"Typst PDF created successfully: {filepath}")

    def _markdown_to_typst(self, content: str) -> str:
        """Convert Markdown to Typst markup."""
        import re

        lines = content.split('\n')
        result = []
        in_code_block = False
        code_lang = ""
        code_content = []

        for line in lines:
            # Code blocks
            if line.strip().startswith('```'):
                if in_code_block:
                    # End code block
                    code_text = '\n'.join(code_content)
                    if code_lang:
                        result.append(f'```{code_lang}\n{code_text}\n```')
                    else:
                        result.append(f'```\n{code_text}\n```')
                    code_content = []
                    in_code_block = False
                else:
                    # Start code block
                    code_lang = line.strip()[3:].strip()
                    in_code_block = True
                continue

            if in_code_block:
                code_content.append(line)
                continue

            # Headers (Typst uses = for headers)
            if line.startswith('#### '):
                result.append(f'==== {line[5:]}')
            elif line.startswith('### '):
                result.append(f'=== {line[4:]}')
            elif line.startswith('## '):
                result.append(f'== {line[3:]}')
            elif line.startswith('# '):
                result.append(f'= {line[2:]}')

            # Blockquotes
            elif line.startswith('> '):
                result.append(f'#quote[{line[2:]}]')

            # Horizontal rules
            elif line.strip() in ['---', '***', '___']:
                result.append('#line(length: 100%, stroke: gray)')

            # Lists stay mostly the same in Typst
            elif line.strip().startswith('- ') or line.strip().startswith('* '):
                result.append(line)

            # Ordered lists
            elif line.strip() and line.strip()[0].isdigit() and '. ' in line.strip()[:4]:
                result.append(line)

            else:
                # Process inline formatting
                processed = self._process_inline_typst(line)
                result.append(processed)

        return '\n'.join(result)

    def _process_inline_typst(self, text: str) -> str:
        """Process inline markdown formatting for Typst."""
        import re

        # Bold: **text** or __text__ -> *text*
        text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)
        text = re.sub(r'__(.+?)__', r'*\1*', text)

        # Italic: *text* or _text_ -> _text_
        # Be careful not to double-convert bold
        text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'_\1_', text)

        # Inline code stays as `code`
        # Links: [text](url) -> #link("url")[text]
        text = re.sub(r'\[(.+?)\]\((.+?)\)', r'#link("\2")[\1]', text)

        # Images: ![alt](url) -> #image("url")
        text = re.sub(r'!\[(.+?)\]\((.+?)\)', r'#image("\2")', text)

        return text

    def _create_pdf_pandoc(self, filepath: Path, title: str, content: str, author: str):
        """Create PDF using Pandoc → LaTeX → PDF pipeline."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create markdown file with YAML frontmatter
            md_file = tmpdir / "document.md"
            md_content = f"""---
title: "{title}"
author: "{author}"
date: "{datetime.now().strftime('%Y-%m-%d')}"
geometry: margin=1in
fontsize: 11pt
---

{content}
"""
            md_file.write_text(md_content, encoding='utf-8')

            # Run pandoc to create PDF directly (uses pdflatex internally)
            output_pdf = tmpdir / "output.pdf"

            cmd = [
                'pandoc',
                str(md_file),
                '-o', str(output_pdf),
                '--pdf-engine=pdflatex',
                '-V', 'colorlinks=true',
                '-V', 'linkcolor=blue',
                '-V', 'urlcolor=blue',
                '--highlight-style=tango'
            ]

            logger.info(f"Running pandoc: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                logger.error(f"Pandoc error: {result.stderr}")
                raise Exception(f"Pandoc failed: {result.stderr}")

            # Copy to final destination
            shutil.copy(output_pdf, filepath)

            logger.info(f"Pandoc PDF created successfully: {filepath}")

    def _create_pdf_reportlab(self, filepath: Path, title: str, content: str, author: str, is_markdown: bool):
        """Create PDF using ReportLab."""
        doc = SimpleDocTemplate(
            str(filepath),
            pagesize=letter,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=72
        )

        styles = getSampleStyleSheet()

        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            spaceAfter=30,
            textColor=colors.darkblue
        )

        body_style = ParagraphStyle(
            'CustomBody',
            parent=styles['Normal'],
            fontSize=11,
            leading=14,
            spaceAfter=12
        )

        code_style = ParagraphStyle(
            'Code',
            parent=styles['Normal'],
            fontSize=9,
            fontName='Courier',
            backColor=colors.Color(0.95, 0.95, 0.95),
            leftIndent=20,
            rightIndent=20,
            spaceAfter=12
        )

        # Build document
        story = []

        # Title
        story.append(Paragraph(title, title_style))
        story.append(Spacer(1, 12))

        # Author and date
        meta_style = ParagraphStyle('Meta', parent=styles['Normal'], fontSize=9, textColor=colors.gray)
        story.append(Paragraph(f"By: {author} | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", meta_style))
        story.append(Spacer(1, 24))

        # Process content
        if is_markdown:
            story.extend(self._process_markdown_reportlab(content, styles, body_style, code_style))
        else:
            # Plain text - just paragraphs
            for para in content.split('\n\n'):
                if para.strip():
                    para_text = para.replace('\n', '<br/>')
                    story.append(Paragraph(para_text, body_style))
                    story.append(Spacer(1, 6))

        doc.build(story)

    def _process_markdown_reportlab(self, content: str, styles, body_style, code_style):
        """Process markdown content for ReportLab."""
        from reportlab.platypus import Paragraph, Spacer, Preformatted

        story = []
        lines = content.split('\n')
        i = 0
        in_code_block = False
        code_content = []

        while i < len(lines):
            line = lines[i]

            # Code blocks
            if line.strip().startswith('```'):
                if in_code_block:
                    # End code block
                    code_text = '\n'.join(code_content)
                    story.append(Preformatted(code_text, code_style))
                    story.append(Spacer(1, 12))
                    code_content = []
                    in_code_block = False
                else:
                    # Start code block
                    in_code_block = True
                i += 1
                continue

            if in_code_block:
                code_content.append(line)
                i += 1
                continue

            # Headers
            if line.startswith('# '):
                story.append(Paragraph(self._escape_html(line[2:]), styles['Heading1']))
                story.append(Spacer(1, 12))
            elif line.startswith('## '):
                story.append(Paragraph(self._escape_html(line[3:]), styles['Heading2']))
                story.append(Spacer(1, 10))
            elif line.startswith('### '):
                story.append(Paragraph(self._escape_html(line[4:]), styles['Heading3']))
                story.append(Spacer(1, 8))
            elif line.startswith('#### '):
                story.append(Paragraph(self._escape_html(line[5:]), styles['Heading4']))
                story.append(Spacer(1, 6))

            # Blockquotes
            elif line.startswith('> '):
                quote_style = ParagraphStyle(
                    'Quote',
                    parent=body_style,
                    leftIndent=30,
                    textColor=colors.gray,
                    fontName='Times-Italic'
                )
                story.append(Paragraph(self._escape_html(line[2:]), quote_style))
                story.append(Spacer(1, 6))

            # Unordered lists
            elif line.strip().startswith('- ') or line.strip().startswith('* '):
                bullet_text = '• ' + self._format_inline(line.strip()[2:])
                list_style = ParagraphStyle('List', parent=body_style, leftIndent=20)
                story.append(Paragraph(bullet_text, list_style))

            # Ordered lists
            elif line.strip() and line.strip()[0].isdigit() and '. ' in line:
                parts = line.strip().split('. ', 1)
                if len(parts) == 2 and parts[0].isdigit():
                    list_text = f"{parts[0]}. {self._format_inline(parts[1])}"
                    list_style = ParagraphStyle('OList', parent=body_style, leftIndent=20)
                    story.append(Paragraph(list_text, list_style))
                else:
                    if line.strip():
                        story.append(Paragraph(self._format_inline(line), body_style))

            # Horizontal rule
            elif line.strip() in ['---', '***', '___']:
                from reportlab.platypus import HRFlowable
                story.append(HRFlowable(width="100%", thickness=1, color=colors.gray))
                story.append(Spacer(1, 12))

            # Regular paragraph
            elif line.strip():
                story.append(Paragraph(self._format_inline(line), body_style))

            # Empty line
            else:
                story.append(Spacer(1, 6))

            i += 1

        return story

    def _format_inline(self, text: str) -> str:
        """Format inline markdown (bold, italic, code, links)."""
        import re

        # Escape HTML first
        text = self._escape_html(text)

        # Bold: **text** or __text__
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)

        # Italic: *text* or _text_
        text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
        text = re.sub(r'_(.+?)_', r'<i>\1</i>', text)

        # Inline code: `code`
        text = re.sub(r'`(.+?)`', r'<font face="Courier" size="9">\1</font>', text)

        # Links: [text](url) - just show text
        text = re.sub(r'\[(.+?)\]\(.+?\)', r'<u>\1</u>', text)

        return text

    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        return (text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;'))

    def _create_pdf_simple(self, filepath: Path, title: str, content: str, author: str):
        """Create a simple PDF without external tools (basic fallback)."""
        pdf_content = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 200 >>
stream
BT
/F1 24 Tf
50 750 Td
({title}) Tj
/F1 12 Tf
0 -30 Td
(By: {author}) Tj
0 -20 Td
(Content available in attached text) Tj
ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000266 00000 n
0000000518 00000 n
trailer
<< /Size 6 /Root 1 0 R >>
startxref
595
%%EOF"""

        filepath.write_text(pdf_content)


class LaTeXCompilerSkill(BaseSkill):
    """Skill for compiling LaTeX documents to PDF."""

    name = "compile_latex"
    description = "Compile a LaTeX document to PDF using pdflatex."
    version = "1.0.0"

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.output_dir = Path(config.get('output_dir', './output')) if config else Path('./output')
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "latex_content": {
                    "type": "string",
                    "description": "The LaTeX document content"
                },
                "filename": {
                    "type": "string",
                    "description": "Output filename (without extension)"
                }
            },
            "required": ["latex_content", "filename"]
        }

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Compile LaTeX to PDF."""
        latex_content = params.get('latex_content', '')
        filename = params.get('filename', 'document')

        if not latex_content:
            return {"success": False, "error": "No LaTeX content provided"}

        if not PDFLATEX_AVAILABLE:
            return {"success": False, "error": "pdflatex not installed. Please install a LaTeX distribution (e.g., MiKTeX or TeX Live)"}

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir = Path(tmpdir)

                # Write LaTeX file
                tex_file = tmpdir / f"{filename}.tex"
                tex_file.write_text(latex_content, encoding='utf-8')

                # Run pdflatex (twice for references)
                for _ in range(2):
                    result = subprocess.run(
                        ['pdflatex', '-interaction=nonstopmode', str(tex_file)],
                        cwd=str(tmpdir),
                        capture_output=True,
                        text=True,
                        timeout=60
                    )

                pdf_file = tmpdir / f"{filename}.pdf"
                if not pdf_file.exists():
                    return {"success": False, "error": f"PDF not generated. LaTeX errors: {result.stdout[-1000:]}"}

                # Copy to output
                output_path = self.output_dir / f"{filename}.pdf"
                shutil.copy(pdf_file, output_path)

                return {
                    "success": True,
                    "result": {
                        "message": f"LaTeX compiled successfully",
                        "filename": f"{filename}.pdf",
                        "filepath": str(output_path),
                        "size_bytes": output_path.stat().st_size
                    }
                }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "LaTeX compilation timed out"}
        except Exception as e:
            return {"success": False, "error": f"LaTeX compilation failed: {str(e)}"}


class DocumentConverterSkill(BaseSkill):
    """Skill for converting documents between formats using Pandoc."""

    name = "convert_document"
    description = "Convert documents between formats (markdown, html, docx, pdf, latex) using Pandoc."
    version = "1.0.0"

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.output_dir = Path(config.get('output_dir', './output')) if config else Path('./output')
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The document content to convert"
                },
                "from_format": {
                    "type": "string",
                    "enum": ["markdown", "html", "latex", "rst"],
                    "description": "Source format"
                },
                "to_format": {
                    "type": "string",
                    "enum": ["pdf", "html", "docx", "latex", "markdown"],
                    "description": "Target format"
                },
                "filename": {
                    "type": "string",
                    "description": "Output filename (without extension)"
                }
            },
            "required": ["content", "from_format", "to_format", "filename"]
        }

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Convert document between formats."""
        content = params.get('content', '')
        from_format = params.get('from_format', 'markdown')
        to_format = params.get('to_format', 'pdf')
        filename = params.get('filename', 'converted')

        if not content:
            return {"success": False, "error": "No content provided"}

        if not PANDOC_AVAILABLE:
            return {"success": False, "error": "Pandoc not installed. Please install Pandoc."}

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir = Path(tmpdir)

                # Determine extensions
                ext_map = {'markdown': 'md', 'html': 'html', 'latex': 'tex', 'rst': 'rst', 'pdf': 'pdf', 'docx': 'docx'}
                input_ext = ext_map.get(from_format, 'txt')
                output_ext = ext_map.get(to_format, 'txt')

                # Write input file
                input_file = tmpdir / f"input.{input_ext}"
                input_file.write_text(content, encoding='utf-8')

                # Output file
                output_file = tmpdir / f"output.{output_ext}"

                # Build pandoc command
                cmd = ['pandoc', str(input_file), '-f', from_format, '-o', str(output_file)]

                if to_format == 'pdf':
                    cmd.extend(['--pdf-engine=pdflatex'])

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

                if result.returncode != 0:
                    return {"success": False, "error": f"Pandoc failed: {result.stderr}"}

                # Copy to output dir
                final_path = self.output_dir / f"{filename}.{output_ext}"
                shutil.copy(output_file, final_path)

                return {
                    "success": True,
                    "result": {
                        "message": f"Document converted from {from_format} to {to_format}",
                        "filename": f"{filename}.{output_ext}",
                        "filepath": str(final_path),
                        "size_bytes": final_path.stat().st_size
                    }
                }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Conversion timed out"}
        except Exception as e:
            return {"success": False, "error": f"Conversion failed: {str(e)}"}
