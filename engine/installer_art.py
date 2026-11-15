"""The pictures the installers show, drawn at build time from the brand's own mark: the disk image's window
background (a cream page with an arrow from the app to the Applications folder and two lines under them) and the
Windows setup's side image and small header image (the brand colour with the mark).

The colours are the installer mockups' (cream, brass and the brand's deep red); the words are passed in, so the
wording lives with the build that uses it. Everything is drawn larger and reduced, so the edges are smooth."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from engine import brandmark

CREAM = (0xFB, 0xF4, 0xE6)
INK = (0x2A, 0x0C, 0x10)
BRASS = (0xB5, 0x98, 0x59)
BRAND = (0x74, 0x1E, 0x25)
ON_BRAND = (0xFF, 0xF2, 0xD8)
WHITE = (0xFF, 0xFF, 0xFF)

#: The disk image's window (in points) and where its two icons sit (their centres, as the Finder places them).
DMG_WINDOW = (620, 340)
DMG_ICON_SIZE = 112
DMG_APP_CENTER = (155, 126)
DMG_APPLICATIONS_CENTER = (465, 126)
#: The side image of the setup's welcome and finished pages, and its sizes for a larger display scale (Inno Setup's
#: own steps: 100% and 200%).
WIZARD_SIDE = (164, 314)
WIZARD_SIDE_LARGE = (328, 628)
#: The small header image of the setup's inner pages.
WIZARD_SMALL = (55, 55)
WIZARD_SMALL_LARGE = (110, 106)

_FONT_FILES = (
    "/System/Library/Fonts/SFNS.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def font(size: int) -> Any:
    """A readable system face at a pixel size; the drawing library's own face when none of the usual ones is there."""
    from PIL import ImageFont

    for path in _FONT_FILES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:  # an older drawing library has only its one small face
        return ImageFont.load_default()


def _blend(front: tuple[int, int, int], back: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(round(f * amount + b * (1 - amount)) for f, b in zip(front, back, strict=True))  # type: ignore[return-value]


def dmg_background(scale: int, lines: Sequence[str]) -> Any:
    """The disk image window's background at 1x or 2x: cream, a brass arrow between the two icon places, and the two
    lines centred near the bottom (the first larger, the second quieter)."""
    from PIL import Image, ImageDraw

    width, height = DMG_WINDOW
    big = 4 * scale
    picture = Image.new("RGB", (width * big, height * big), CREAM)
    draw = ImageDraw.Draw(picture)
    stroke = 4 * big
    y = DMG_APP_CENTER[1] + 2
    start, end, head = 238 * big, 374 * big, 14 * big
    # The shaft and the two sides of the head, with round ends.
    for a, b in (((start, y * big), (end, y * big)), ((end, y * big), (end - head, y * big - 12 * big))):
        draw.line([a, b], fill=BRASS, width=stroke)
    draw.line([(end, y * big), (end - head, y * big + 12 * big)], fill=BRASS, width=stroke)
    for centre in (
        (start, y * big),
        (end, y * big),
        (end - head, y * big - 12 * big),
        (end - head, y * big + 12 * big),
    ):
        draw.ellipse(
            [centre[0] - stroke // 2, centre[1] - stroke // 2, centre[0] + stroke // 2, centre[1] + stroke // 2],
            fill=BRASS,
        )
    first, second = lines
    for text, size, colour, bottom in (
        (first, 19, INK, 340 - 34 - 24),
        (second, 13, _blend(INK, CREAM, 0.72), 340 - 34),
    ):
        face = font(size * big)
        box = draw.textbbox((0, 0), text, font=face)
        draw.text(((width * big - (box[2] - box[0])) / 2 - box[0], bottom * big - box[3]), text, font=face, fill=colour)
    return picture.resize((width * scale, height * scale), Image.LANCZOS)


def wizard_side(size: tuple[int, int], name: str, version_line: str) -> Any:
    """The setup's side image: the brand colour, the mark, the name and, at the foot, the version."""
    from PIL import Image, ImageDraw

    width, height = size
    unit = width / WIZARD_SIDE[0]
    big = 4
    picture = Image.new("RGB", (width * big, height * big), BRAND)
    mark = brandmark.render(brandmark.mark_svg(), round(72 * unit * big), template=False)
    pad = round(22 * unit * big)
    picture.paste(mark, (pad, round(28 * unit * big)), mark)
    draw = ImageDraw.Draw(picture)
    top = round((28 + 72 + 14) * unit * big)
    draw.text((pad, top), name, font=font(round(22 * unit * big)), fill=ON_BRAND)
    small = font(round(12 * unit * big))
    box = draw.textbbox((0, 0), version_line, font=small)
    draw.text(
        (pad, height * big - round(28 * unit * big) - box[3]),
        version_line,
        font=small,
        fill=_blend(ON_BRAND, BRAND, 0.8),
    )
    return picture.resize((width, height), Image.LANCZOS)


def wizard_small(size: tuple[int, int]) -> Any:
    """The setup's small header image: the mark on the page's own white."""
    from PIL import Image

    width, height = size
    side = min(width, height)
    mark = brandmark.render(brandmark.mark_svg(), side, template=False)
    picture = Image.new("RGB", (width, height), WHITE)
    picture.paste(mark, ((width - side) // 2, (height - side) // 2), mark)
    return picture


def write_dmg_background(folder: Path, lines: Sequence[str], stem: str = "dmg-background") -> tuple[Path, Path]:
    """The window background at 1x and 2x as `<stem>.png` and `<stem>@2x.png` (72 and 144 dpi, which is how the system
    tells the two apart when it joins them); returns both paths."""
    folder.mkdir(parents=True, exist_ok=True)
    one, two = folder / f"{stem}.png", folder / f"{stem}@2x.png"
    dmg_background(1, lines).save(one, dpi=(72, 72))
    dmg_background(2, lines).save(two, dpi=(144, 144))
    return one, two


def write_wizard_images(folder: Path, name: str, version_line: str) -> dict[str, Path]:
    """The setup's pictures as 24-bit bitmaps (the one form every Inno Setup version reads): the side image at 164 x 314
    and 328 x 628, and the small image at 55 x 55 and 110 x 106. Returns each by its role."""
    folder.mkdir(parents=True, exist_ok=True)
    made = {
        "side": folder / "side.bmp",
        "side_large": folder / "side@2x.bmp",
        "small": folder / "small.bmp",
        "small_large": folder / "small@2x.bmp",
    }
    wizard_side(WIZARD_SIDE, name, version_line).save(made["side"])
    wizard_side(WIZARD_SIDE_LARGE, name, version_line).save(made["side_large"])
    wizard_small(WIZARD_SMALL).save(made["small"])
    wizard_small(WIZARD_SMALL_LARGE).save(made["small_large"])
    return made
