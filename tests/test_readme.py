"""The README screenshots: every image it points to exists, light and dark come in pairs, both languages show the same pictures."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def images(readme):
    return re.findall(r"docs/images/([\w-]+\.png)", (ROOT / readme).read_text(encoding="utf-8"))


def test_every_screenshot_exists_and_themes_come_in_pairs():
    names = set(images("README.md"))
    assert len(names) >= 10
    for n in names:
        f = ROOT / "docs" / "images" / n
        assert f.is_file() and f.stat().st_size > 5000, n
        if n.endswith("-light.png"):
            assert (ROOT / "docs" / "images" / n.replace("-light", "-dark")).is_file(), n


def test_both_languages_show_the_same_pictures():
    assert sorted(images("README.md")) == sorted(images("README.pt-BR.md"))


def test_the_images_are_not_huge():
    assert sum(f.stat().st_size for f in (ROOT / "docs" / "images").glob("*.png")) < 3_000_000          # the repository should stay light to clone
