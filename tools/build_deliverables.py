"""
Collate deliverables: decode doc PDF exports, render repo Markdown to PDF via a
headless browser, copy the two introspection modules as .txt, and extract text
from every PDF for review.

  python tools/build_deliverables.py <out_dir> <export_json> [<export_json> ...]
"""
import base64
import html
import json
import pathlib
import shutil
import subprocess
import sys

import markdown
from pypdf import PdfReader

ROOT = pathlib.Path(__file__).resolve().parents[1]
BROWSER = pathlib.Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
MD_FILES = {
    "VERIFIED_FACTS.md": "Verified Facts Ledger.pdf",
    "README.md": "Repository README.pdf",
    "examples/README.md": "Examples README.pdf",
}
CSS = """
body { font-family: 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 10.5pt; line-height: 1.45;
       color: #1d1d1f; max-width: 7.2in; margin: 0 auto; }
h1 { font-size: 20pt; margin: 0 0 8pt; } h2 { font-size: 14pt; margin: 18pt 0 6pt; border-bottom: 1px solid #ddd; }
h3 { font-size: 12pt; margin: 14pt 0 4pt; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt; font-size: 9pt; page-break-inside: auto; }
th, td { border: 1px solid #ccc; padding: 4pt 6pt; vertical-align: top; text-align: left; }
th { background: #f2f4f7; } tr { page-break-inside: avoid; }
code { font-family: Consolas, 'Courier New', monospace; font-size: 9pt; background: #f4f4f6; padding: 0 2pt; }
pre { background: #f4f4f6; padding: 8pt; font-size: 8.5pt; white-space: pre-wrap; border-radius: 4pt; }
pre code { background: none; padding: 0; }
a { color: #1a5fb4; text-decoration: none; }
@page { size: Letter; margin: 0.7in; }
"""


def md_to_pdf(src: pathlib.Path, dst: pathlib.Path, scratch: pathlib.Path) -> None:
    body = markdown.markdown(src.read_text(encoding="utf-8"), extensions=["tables", "fenced_code", "sane_lists"])
    page = scratch / (dst.stem + ".html")
    page.write_text(f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(dst.stem)}</title>"
                    f"<style>{CSS}</style></head><body>{body}</body></html>", encoding="utf-8")
    subprocess.run([str(BROWSER), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={dst}", page.as_uri()], check=True, capture_output=True, timeout=120)


def main() -> None:
    out = pathlib.Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    text_dir = out / "_text"
    text_dir.mkdir(exist_ok=True)
    scratch = out / "_html"
    scratch.mkdir(exist_ok=True)

    for export in sys.argv[2:]:  # docs connector PDF exports (JSON with base64)
        data = json.loads(pathlib.Path(export).read_text(encoding="utf-8"))["data"]
        dst = out / data["name"].replace(":", " -")
        dst.write_bytes(base64.b64decode(data["bytes_b64"]))
        print(f"doc pdf   {dst.name}  {dst.stat().st_size:,} bytes")

    for src, name in MD_FILES.items():
        dst = out / name
        md_to_pdf(ROOT / src, dst, scratch)
        print(f"md pdf    {dst.name}  {dst.stat().st_size:,} bytes")

    for src in ("introspect/dh_introspect.py", "introspect/dh_introspect_client.py"):
        dst = out / (pathlib.Path(src).name + ".txt")
        shutil.copyfile(ROOT / src, dst)
        print(f"module    {dst.name}  {dst.stat().st_size:,} bytes")

    for pdf in sorted(out.glob("*.pdf")):
        reader = PdfReader(str(pdf))
        images = sum(1 for p in reader.pages for k, v in (p.get("/Resources", {}).get("/XObject", {}) or {}).items())
        (text_dir / (pdf.stem + ".txt")).write_text("\n".join(p.extract_text() or "" for p in reader.pages),
                                                    encoding="utf-8")
        print(f"text      {pdf.stem}.txt  ({len(reader.pages)} pages, {images} embedded objects)")
    shutil.rmtree(scratch)


if __name__ == "__main__":
    main()
