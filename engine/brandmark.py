"""The brand mark drawn as a small picture for the menu bar and the tray, from the brand's own SVG file.

Nothing about the shape is written here: the paths, colours and gradients are read from the SVG the screens use, and
only a small part of SVG is understood (straight lines, curves, closed shapes, a rounded square and linear gradients),
which is all that file holds. On the Mac the picture is a one-colour template (the shape in black on nothing, which the
menu bar tints for light and dark); in the Windows tray it is full colour."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

#: The brand folder in a checkout, and in the frozen app (it is bundled at the same relative place).
BRAND_FOLDER = Path(__file__).resolve().parents[1] / "web" / "src" / "assets" / "brand"
MARK_FILE = "mark-day.svg"
#: Drawn this many times larger and then reduced, so the edges are smooth.
SUPERSAMPLE = 4

_TOKEN = re.compile(r"[A-Za-z]|-?\d*\.?\d+(?:e-?\d+)?")
_STEPS = 12


def mark_svg(folder: Path = BRAND_FOLDER, name: str = MARK_FILE) -> str:
    """The text of the brand's mark file."""
    return (folder / name).read_text(encoding="utf-8")


def flatten(d: str) -> list[list[tuple[float, float]]]:
    """A path's outlines as lists of points: lines, quadratic and cubic curves, closed by Z (absolute commands)."""
    tokens = _TOKEN.findall(d)
    shapes: list[list[tuple[float, float]]] = []
    points: list[tuple[float, float]] = []
    i, command, current = 0, "", (0.0, 0.0)

    def number() -> float:
        nonlocal i
        i += 1
        return float(tokens[i - 1])

    def curve(*controls: tuple[float, float]) -> None:
        nonlocal current
        start, end = current, controls[-1]
        for step in range(1, _STEPS + 1):
            t = step / _STEPS
            u = 1 - t
            if len(controls) == 2:
                (cx, cy) = controls[0]
                x = u * u * start[0] + 2 * u * t * cx + t * t * end[0]
                y = u * u * start[1] + 2 * u * t * cy + t * t * end[1]
            else:
                (c1x, c1y), (c2x, c2y) = controls[0], controls[1]
                x = u**3 * start[0] + 3 * u * u * t * c1x + 3 * u * t * t * c2x + t**3 * end[0]
                y = u**3 * start[1] + 3 * u * u * t * c1y + 3 * u * t * t * c2y + t**3 * end[1]
            points.append((x, y))
        current = end

    while i < len(tokens):
        if tokens[i].isalpha():
            command = tokens[i]
            i += 1
            if command == "Z":
                if points:
                    shapes.append(points)
                points = []
                continue
        if command == "M":
            if points:
                shapes.append(points)
            current = (number(), number())
            points = [current]
            command = "L"
        elif command == "L":
            current = (number(), number())
            points.append(current)
        elif command == "Q":
            curve((number(), number()), (number(), number()))
        elif command == "C":
            curve((number(), number()), (number(), number()), (number(), number()))
        else:
            raise ValueError(f"The mark uses a path command this reader does not know: {command!r}")
    if points:
        shapes.append(points)
    return shapes


def _gradient(root: ET.Element, ident: str, box: tuple[float, float, float, float], size: int, scale: float) -> Any:
    """A linear gradient filling a box, as a picture the size of the canvas."""
    from PIL import Image

    element = next(e for e in root.iter("linearGradient") if e.get("id") == ident)
    x1, y1, x2, y2 = (float(element.get(k, d)) for k, d in (("x1", "0"), ("y1", "0"), ("x2", "1"), ("y2", "0")))
    stops = []
    for position, stop in enumerate(element.iter("stop")):
        offset = float(stop.get("offset", "0" if position == 0 else "1"))
        stops.append((offset, _colour(stop.get("stop-color", "#000000"))))
    left, top, width, height = box
    image = Image.new("RGB", (size, size))
    pixels = image.load()
    dx, dy = (x2 - x1) * width, (y2 - y1) * height
    length = dx * dx + dy * dy or 1.0
    for py in range(size):
        for px in range(size):
            t = (((px + 0.5) / scale - left - x1 * width) * dx + ((py + 0.5) / scale - top - y1 * height) * dy) / length
            t = min(1.0, max(0.0, t))
            for (o1, c1), (o2, c2) in zip(stops, stops[1:], strict=False):
                if t <= o2 or (o2, c2) == stops[-1]:
                    f = 0.0 if o2 == o1 else min(1.0, max(0.0, (t - o1) / (o2 - o1)))
                    pixels[px, py] = tuple(round(a + (b - a) * f) for a, b in zip(c1, c2, strict=True))
                    break
    return image


def _colour(text: str) -> tuple[int, int, int]:
    text = text.lstrip("#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _bounds(shapes: list[list[tuple[float, float]]]) -> tuple[float, float, float, float]:
    xs = [p[0] for s in shapes for p in s]
    ys = [p[1] for s in shapes for p in s]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def render(svg: str, size: int, *, template: bool) -> Any:
    """The mark as a square RGBA picture; template means the shape alone in black on nothing."""
    from PIL import Image, ImageChops, ImageDraw

    root = ET.fromstring(re.sub(r'\sxmlns="[^"]*"', "", svg, count=1))
    view = [float(v) for v in root.get("viewBox", "0 0 1024 1024").split()]
    big = size * SUPERSAMPLE
    scale = big / view[2]
    parts = {e.get("id"): e for e in root.iter() if e.get("id")}

    def mask(shapes: list[list[tuple[float, float]]]) -> Any:
        layer = Image.new("L", (big, big), 0)
        draw = ImageDraw.Draw(layer)
        for shape in shapes:
            draw.polygon([(x * scale, y * scale) for x, y in shape], fill=255)
        return layer

    def outline(name: str) -> list[list[tuple[float, float]]]:
        return flatten(parts[name].get("d", ""))

    def paint(layer_mask: Any, fill: str, shapes: list[list[tuple[float, float]]]) -> Any:
        if fill.startswith("url(#"):
            source = _gradient(root, fill[5:-1], _bounds(shapes), big, scale)
        else:
            source = Image.new("RGB", (big, big), _colour(fill))
        return source, layer_mask

    if template:
        body = mask(outline("thimble") + outline("rim"))
        cut = mask(outline("bow"))
        shape = ImageChops.subtract(body, cut)
        out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        out.putalpha(shape)
        return out.resize((size, size), Image.LANCZOS)

    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ground = parts["background"]
    gx, gy, gw, gh = (float(ground.get(k, "0")) for k in ("x", "y", "width", "height"))
    ground_mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(ground_mask).rounded_rectangle(
        (gx * scale, gy * scale, (gx + gw) * scale, (gy + gh) * scale),
        radius=float(ground.get("rx", "0")) * scale,
        fill=255,
    )
    source, _ = paint(ground_mask, ground.get("fill", "#000000"), [[(gx, gy), (gx + gw, gy + gh)]])
    canvas.paste(source, (0, 0), ground_mask)
    for name in ("thimble", "bow", "rim"):
        shapes = outline(name)
        source, layer_mask = paint(mask(shapes), parts[name].get("fill", "#000000"), shapes)
        canvas.paste(source, (0, 0), layer_mask)
    return canvas.resize((size, size), Image.LANCZOS)


#: The sizes (in pixels) the Windows icon file carries, and the one the Mac's icon file is drawn from.
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICNS_PIXELS = 1024


def write_ico(target: Path, svg: str | None = None) -> Path:
    """The Windows icon file: the full-colour mark at every size the system asks for."""
    target.parent.mkdir(parents=True, exist_ok=True)
    picture = render(svg or mark_svg(), max(ICO_SIZES), template=False)
    picture.save(target, format="ICO", sizes=[(n, n) for n in ICO_SIZES])
    return target


def write_icns(target: Path, svg: str | None = None) -> Path:
    """The Mac icon file, drawn from one large picture of the full-colour mark."""
    target.parent.mkdir(parents=True, exist_ok=True)
    render(svg or mark_svg(), ICNS_PIXELS, template=False).save(target, format="ICNS")
    return target
