#!/usr/bin/env python3
"""Bundle the viewer into ONE self-contained HTML file (shareable, works offline).

Usage:
  python3 scripts/export_viewer.py                 # graph only -> dist/SubjectKG-viewer.html
  python3 scripts/export_viewer.py S001            # + that student's mastery overlay

Runs build_kg.py (and export_student_overlay.py if a student is given) first, so the
bundle is always current.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    student = sys.argv[1] if len(sys.argv) > 1 else None
    subprocess.run([sys.executable, ROOT / "scripts" / "build_kg.py"], check=True,
                   capture_output=True)
    if student:
        r = subprocess.run([sys.executable, ROOT / "scripts" / "export_student_overlay.py",
                            student], capture_output=True, text=True)
        if r.returncode:
            print(r.stdout + r.stderr)
            return 1

    html = (ROOT / "viewer" / "index.html").read_text()
    kg = (ROOT / "viewer" / "kg-data.js").read_text()
    if student:
        overlay = (ROOT / "viewer" / "student-data.js").read_text()
    else:
        overlay = "window.STUDENT_DATA = null;\n"

    html = html.replace('<script src="kg-data.js"></script>',
                        "<script>\n" + kg + "</script>")
    loader = """  // student-data.js is optional (generated per student); ignore if absent
  const sd = document.createElement('script');
  sd.src = 'student-data.js';
  sd.onerror = () => {}; sd.onload = () => init(true);
  document.head.appendChild(sd);
  let booted = false;"""
    html = html.replace(loader, "  // student overlay inlined for standalone export\n"
                        + overlay + "\n  let booted = false;")
    assert 'src="kg-data.js"' not in html and "window.KG_DATA" in html, "inlining failed"

    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    name = f"SubjectKG-viewer{'-' + student if student else ''}.html"
    out = dist / name
    out.write_text(html)
    print(f"Wrote {out.relative_to(ROOT)} ({len(html) // 1024} KB, "
          f"{'with ' + student + ' overlay' if student else 'no student overlay'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
