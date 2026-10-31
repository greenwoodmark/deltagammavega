import re
from pathlib import Path

import pytest

from tools import build_site, validate_public_build

REPO_ROOT = Path(__file__).resolve().parents[1]
NEW_PAGE = "cpi_prediction_markets.html"
NEW_DATA = "cpi_prediction_markets.json"


def _build(tmp_path: Path) -> Path:
    output = tmp_path / "public"
    build_site.build_variant(REPO_ROOT, output)
    return output


def test_build_includes_new_page_and_data(tmp_path):
    output = _build(tmp_path)
    assert (output / NEW_PAGE).is_file()
    assert (output / "data" / NEW_DATA).is_file()


def test_validate_public_build_passes_with_new_artifacts(tmp_path):
    output = _build(tmp_path)
    # Should not raise.
    validate_public_build.validate(output)


def _logo_anchors(html: str):
    """Return [(href, letter)] for every <a class="logo-letter"> wrapping a <text>."""
    anchors = re.findall(
        r'<a class="logo-letter"[^>]*href="([^"]+)"[^>]*>\s*<text[^>]*>([^<]+)</text>\s*</a>',
        html,
    )
    return anchors


def _count_svg_sections(html: str):
    """Split the index into the nav SVG and hero SVG for independent assertions."""
    svgs = re.findall(r"<svg.*?</svg>", html, flags=re.DOTALL)
    assert len(svgs) == 2, f"expected exactly 2 wordmark SVGs, found {len(svgs)}"
    return svgs


def test_first_e_links_to_new_page_in_both_svgs(tmp_path):
    output = _build(tmp_path)
    html = (output / "index.html").read_text(encoding="utf-8")
    nav_svg, hero_svg = _count_svg_sections(html)

    for name, svg in (("nav", nav_svg), ("hero", hero_svg)):
        anchors = _logo_anchors(svg)
        letters = {letter: href for href, letter in anchors}
        # Exactly the D and the first e are linked.
        assert set(letters) == {"D", "e"}, f"{name} SVG linked letters: {letters}"
        assert letters["D"] == "cpurnsa.html", f"{name} D href"
        assert letters["e"] == NEW_PAGE, f"{name} e href"
        # No other letter is a logo-letter link (D + e only => 2 anchors per SVG).
        assert len(anchors) == 2, f"{name} SVG has {len(anchors)} logo-letter anchors"

    # And the first linked "e" across the whole document points at the new page.
    all_anchors = _logo_anchors(html)
    e_hrefs = {href for href, letter in all_anchors if letter == "e"}
    assert e_hrefs == {NEW_PAGE}
