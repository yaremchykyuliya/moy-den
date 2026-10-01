"""Баннеры для экранов бота — в стиле PDF-гайдов (палитра «Олива»).

Запуск: python guides/banners.py  →  products/banners/*.png
Текст баннеров — в BANNERS ниже. Слово в *звёздочках* выйдет курсивом.
"""
import html
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build import PALETTES, find_chrome  # noqa: E402

OUT = HERE.parent / "products" / "banners"
W, H = 1280, 720

BANNERS = {
    "start": ("Красивая жизнь считается", "Нейросеть, *которая тебя знает*", "поездки · покупки · деньги · сообщения"),
    "more": ("Всё, что есть в боте", "Гайды, ассистент *и шаблоны*", "5 гайдов бесплатно"),
    "free": ("Бесплатно", "Пять гайдов — *пять задач*", "каждый — результат за несколько минут"),
    "assistant": ("Личный ИИ-ассистент", "Один раз рассказать — *и не объяснять*", "10 ассистентов с моими правилами"),
    "library": ("Библиотека запросов", "100 запросов, *готовых к делу*", "вставляешь своё — получаешь ответ"),
}

PAGE = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><style>
{fonts}
:root{{{palette}}}
*{{box-sizing:border-box;margin:0}}
html,body{{width:{w}px;height:{h}px;overflow:hidden}}
body{{background:var(--paper);position:relative;font-family:'Manrope',sans-serif;color:var(--ink)}}
.mist{{position:absolute;right:-170px;top:-230px;width:720px;height:720px;border-radius:50%;background:var(--green-mist)}}
.dot{{position:absolute;right:150px;top:150px;width:92px;height:92px;border-radius:50%;background:var(--green)}}
.ring{{position:absolute;right:96px;top:96px;width:200px;height:200px;border-radius:50%;border:1.5px solid var(--green);opacity:.35}}
.k{{position:absolute;left:96px;top:92px;font:700 22px 'Manrope',sans-serif;letter-spacing:.24em;text-transform:uppercase;color:var(--green)}}
h1{{position:absolute;left:92px;bottom:150px;width:900px;font:600 92px/1.0 'Cormorant Garamond',Georgia,serif;color:var(--ink);letter-spacing:-.005em}}
h1 i{{font-style:italic;font-weight:500;color:var(--green-deep)}}
.s{{position:absolute;left:96px;bottom:84px;font:500 26px 'Manrope',sans-serif;color:var(--ink-soft);letter-spacing:.02em}}
.line{{position:absolute;left:96px;right:96px;bottom:136px;height:0}}
</style></head><body>
<div class="mist"></div><div class="ring"></div><div class="dot"></div>
<div class="k">{kicker}</div><h1>{title}</h1><div class="s">{sub}</div>
</body></html>"""


def render(chrome: str, name: str, kicker: str, title: str, sub: str) -> Path:
    palette = ";".join(f"--{k}:{v}" for k, v in PALETTES["olive"].items())
    title_html = re.sub(r"\*(.+?)\*", r"<i>\1</i>", html.escape(title))
    fonts = (HERE / "fonts" / "fonts.css").read_text(encoding="utf-8").replace("url(fonts/", f"url({(HERE / 'fonts').as_uri()}/")
    page = PAGE.format(fonts=fonts, palette=palette, w=W, h=H, kicker=html.escape(kicker),
                       title=title_html, sub=html.escape(sub))
    out = OUT / f"{name}.png"
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(page)
        tmp = Path(f.name)
    try:
        subprocess.run([chrome, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                        f"--window-size={W},{H}", "--virtual-time-budget=4000",
                        f"--screenshot={out}", tmp.as_uri()], check=True, capture_output=True)
    finally:
        tmp.unlink()
    return out


def main() -> None:
    chrome = find_chrome()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (kicker, title, sub) in BANNERS.items():
        out = render(chrome, name, kicker, title, sub)
        print(f"✓ {out.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
