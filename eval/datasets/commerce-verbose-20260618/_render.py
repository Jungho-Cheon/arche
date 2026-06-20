"""_render_src/ 의 HTML 을 PDF/PNG 로 렌더해 corpus/<slug>/ 에 배치.

playwright 독립 Chromium 사용 — 사용자 Chrome 과 무관 (프로필 선택창 회피).
.pdf.html → corpus/<slug>/<basename>.pdf  (A4, print_background)
.png.html → corpus/<slug>/<basename>.png  (1200x800 viewport)

다음 세션에서 코퍼스 갱신 시 재실행 가능하도록 데이터셋에 보존.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "_render_src"
CORPUS = ROOT / "corpus"


def main() -> None:
    pdfs = sorted(SRC.rglob("*.pdf.html"))
    pngs = sorted(SRC.rglob("*.png.html"))
    done = 0
    total = len(pdfs) + len(pngs)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for f in pdfs:
            slug = f.parent.name
            out = CORPUS / slug / f.name[:-5]  # strip ".html" -> ".pdf"
            out.parent.mkdir(parents=True, exist_ok=True)
            page = browser.new_page()
            page.goto(f.as_uri(), wait_until="networkidle")
            page.pdf(path=str(out), format="A4", print_background=True,
                     margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
            page.close()
            done += 1
            print(f"  [{done}/{total} pdf] {out.relative_to(ROOT)} -> {out.stat().st_size}B")
        for f in pngs:
            slug = f.parent.name
            out = CORPUS / slug / f.name[:-5]  # strip ".html" -> ".png"
            out.parent.mkdir(parents=True, exist_ok=True)
            page = browser.new_page(viewport={"width": 1200, "height": 800})
            page.goto(f.as_uri(), wait_until="networkidle")
            page.screenshot(path=str(out))
            page.close()
            done += 1
            print(f"  [{done}/{total} png] {out.relative_to(ROOT)} -> {out.stat().st_size}B")
        browser.close()
    print(f"=== DONE {done}/{total} ===")


if __name__ == "__main__":
    main()
