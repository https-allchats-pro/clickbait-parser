from __future__ import annotations

import tempfile
from pathlib import Path

import qrcode
import qrcode.image.svg


def render_ascii_qr(auth_url: str) -> str:
    import io

    qr = qrcode.QRCode(border=1)
    qr.add_data(auth_url)
    qr.make(fit=True)
    buf = io.StringIO()
    # invert=True → black modules on light terminal backgrounds
    qr.print_ascii(out=buf, invert=True)
    return buf.getvalue().rstrip()


def write_qr_html_page(auth_url: str, *, directory: Path | None = None) -> Path:
    """Write a local HTML page with an embedded SVG QR (scan with VK app)."""
    root = directory or Path(tempfile.mkdtemp(prefix="clickbait-vk-qr-"))
    root.mkdir(parents=True, exist_ok=True)

    factory = qrcode.image.svg.SvgPathImage
    img = qrcode.make(auth_url, image_factory=factory, box_size=12, border=2)
    svg_path = root / "vk-qr.svg"
    img.save(svg_path)
    svg_markup = svg_path.read_text(encoding="utf-8")

    html_path = root / "vk-qr.html"
    html_path.write_text(
        f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>VK QR Login — Clickbait Parser</title>
  <style>
    :root {{ color-scheme: light; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      font-family: "Segoe UI", system-ui, sans-serif;
      background: linear-gradient(160deg, #e8eef5 0%, #f7f4ef 100%);
      color: #1a1a1a;
    }}
    .card {{
      width: min(420px, 92vw);
      padding: 2rem 1.75rem;
      background: #fff;
      border-radius: 16px;
      box-shadow: 0 12px 40px rgba(20, 40, 80, 0.12);
      text-align: center;
    }}
    h1 {{
      margin: 0 0 0.5rem;
      font-size: 1.35rem;
      font-weight: 650;
    }}
    p {{
      margin: 0 0 1.25rem;
      color: #4a5568;
      line-height: 1.45;
      font-size: 0.95rem;
    }}
    .qr {{
      display: inline-flex;
      padding: 12px;
      background: #fff;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
    }}
    .qr svg {{
      width: 280px;
      height: 280px;
      display: block;
    }}
    .hint {{
      margin-top: 1.25rem;
      font-size: 0.8rem;
      color: #718096;
      word-break: break-all;
    }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Вход через VK</h1>
    <p>Откройте приложение VK на телефоне и отсканируйте QR-код.<br/>
    Не открывайте ссылку qr.vk.ru в браузере на компьютере.</p>
    <div class="qr">{svg_markup}</div>
    <p class="hint">{auth_url}</p>
  </div>
</body>
</html>
""",
        encoding="utf-8",
    )
    return html_path
