"""Optional native PDF smoke checks; no validator is a core dependency."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def _one_page_pdf(path: Path) -> None:
    objects = [
        b"%PDF-1.4\n",
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] "
            b"/Resources << >> >>\nendobj\n"
        ),
    ]
    offsets: list[int] = []
    position = len(objects[0])
    for item in objects[1:]:
        offsets.append(position)
        position += len(item)
    output = b"".join(objects)
    output += b"xref\n0 4\n0000000000 65535 f \n"
    output += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    output += (
        f"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n{position}\n%%EOF\n".encode()
    )
    path.write_bytes(output)


@pytest.mark.parametrize("tool", ["qpdf", "pdftoppm"])
def test_selected_pdf_native_tool_accepts_and_processes_a_generated_page(
    tmp_path: Path, tool: str
) -> None:
    executable = shutil.which(tool)
    if executable is None:
        pytest.skip(f"optional PDF tool {tool} is unavailable")
    pdf = tmp_path / "one-page.pdf"
    _one_page_pdf(pdf)
    if tool == "qpdf":
        result = subprocess.run(
            [executable, "--check", str(pdf)],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
    else:
        output_prefix = tmp_path / "rendered"
        result = subprocess.run(
            [
                executable,
                "-f",
                "1",
                "-l",
                "1",
                "-singlefile",
                "-png",
                "-r",
                "72",
                str(pdf),
                str(output_prefix),
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        rendered = output_prefix.with_suffix(".png")
        assert rendered.is_file() and rendered.stat().st_size > 0
