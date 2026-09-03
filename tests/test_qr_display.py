from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from infrastructure.vk.qr_display import render_ascii_qr, write_qr_html_page


class QrDisplayTests(unittest.TestCase):
    def test_write_qr_html_embeds_svg_and_url(self) -> None:
        url = "https://qr.vk.ru/ca?q=test123"
        with tempfile.TemporaryDirectory() as tmp:
            html_path = write_qr_html_page(url, directory=Path(tmp))
            self.assertTrue(html_path.is_file())
            body = html_path.read_text(encoding="utf-8")
            self.assertIn("<svg", body)
            self.assertIn(url, body)
            self.assertIn("отсканируйте qr", body.lower())
            self.assertIn("не открывайте ссылку qr.vk.ru", body.lower())

    def test_ascii_qr_non_empty(self) -> None:
        ascii_qr = render_ascii_qr("https://qr.vk.ru/ca?q=abc")
        self.assertTrue(len(ascii_qr) > 10)


if __name__ == "__main__":
    unittest.main()
