"""
Wrapper subprocess untuk render.js (Observable Plot + jsdom di Node).
exports.md §2: "Observable Plot supports server-side SVG rendering via
its Node-based build" -- modul ini SATU-SATUNYA titik panggil ke Node
dari Python, supaya penanganan error/kontrak I/O konsisten di satu
tempat, tidak diduplikasi di tiap service yang butuh chart.

Kontrak I/O (disepakati saat pengembangan render.js sesi ini):
- stdin: JSON {"chart_type": "gantt"|"budget"|"condition_trend", "data": {...}}
- stdout: SVG mentah (diawali "<svg"), TIDAK ADA apa pun selain itu
- stderr: pesan error/diagnostik (dipakai kalau proses gagal)
- exit code 0 = sukses, non-zero = gagal
"""
from __future__ import annotations

import json
import subprocess
import uuid
from decimal import Decimal
from pathlib import Path

RENDER_JS_PATH = Path(__file__).parent / "chart_renderer" / "render.js"


def _json_default(obj):
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, Decimal):
        # Konversi ke float HANYA untuk keperluan plotting visual (posisi
        # pixel chart) -- BUKAN jalur audit/precision (engineering-rules.md
        # §4 berlaku untuk storage/komputasi model/optimasi, bukan untuk
        # rendering grafis). Angka presisi asli (Decimal) tetap dipakai
        # apa adanya di tabel appendix PDF (dirender langsung dari
        # Django template, tidak lewat JSON/Node sama sekali).
        return float(obj)
    return str(obj)


class ChartRenderError(RuntimeError):
    pass


def render_chart_svg(chart_type: str, data: dict) -> str:
    """Panggil render.js via subprocess, kembalikan string SVG mentah.
    Gagal LOUD (ChartRenderError) kalau exit code != 0 atau output bukan
    SVG valid -- exports.md §5: "never a silent failure"."""
    payload = json.dumps({"chart_type": chart_type, "data": data}, default=_json_default)

    result = subprocess.run(
        ["node", str(RENDER_JS_PATH)],
        input=payload.encode("utf-8"),
        capture_output=True,
        timeout=30,
    )

    if result.returncode != 0:
        raise ChartRenderError(
            f"render.js gagal (chart_type={chart_type}, exit code {result.returncode}): "
            f"{result.stderr.decode('utf-8', errors='replace')}"
        )

    svg = result.stdout.decode("utf-8")
    if not svg.strip().startswith("<svg"):
        raise ChartRenderError(
            f"render.js mengembalikan output yang bukan SVG valid (chart_type={chart_type}): "
            f"{svg[:200]!r}"
        )

    return svg
