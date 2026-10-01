"""Баннеры для экранов бота — в стиле PDF-гайдов (палитра «Олива»).

Запуск: python guides/banners.py  →  products/banners/*.png
         python guides/banners.py peony  →  те же баннеры в другой палитре
Текст баннеров — в BANNERS ниже. Слово в *звёздочках* выйдет курсивом.
Там же собирается аватарка бота (avatar.png) — её загружают в @BotFather.
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
PALETTE = "olive"

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


AVATAR = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{fonts}
:root{{{palette}}}
html,body{{margin:0;width:640px;height:640px;overflow:hidden;background:var(--green-deep)}}
.c{{position:absolute;left:-120px;bottom:-160px;width:560px;height:560px;border-radius:50%;background:var(--green)}}
.d{{position:absolute;right:118px;top:118px;width:74px;height:74px;border-radius:50%;background:var(--paper)}}
.l{{position:absolute;left:0;right:0;top:150px;text-align:center;font:italic 500 330px/1 'Cormorant Garamond',Georgia,serif;color:var(--paper)}}
</style></head><body><div class="c"></div><div class="d"></div><div class="l">{letter}</div></body></html>"""


HEADLESS_SHELL = "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell"


def find_shooter() -> str:
    """Обычный Chrome в режиме --screenshot съедает ~90 px снизу; headless_shell снимает ровно W×H."""
    return HEADLESS_SHELL if Path(HEADLESS_SHELL).is_file() else find_chrome()


def _shot(chrome: str, page: str, out: Path, w: int, h: int) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(page)
        tmp = Path(f.name)
    try:
        subprocess.run([chrome, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                        f"--window-size={w},{h}", "--virtual-time-budget=4000",
                        f"--screenshot={out}", tmp.as_uri()], check=True, capture_output=True)
    finally:
        tmp.unlink()


def _fonts() -> str:
    return (HERE / "fonts" / "fonts.css").read_text(encoding="utf-8").replace("url(fonts/", f"url({(HERE / 'fonts').as_uri()}/")


def _palette(name: str) -> str:
    return ";".join(f"--{k}:{v}" for k, v in PALETTES[name].items())


def render_avatar(chrome: str, out_dir: Path, palette_name: str = PALETTE, letter: str = "Ю") -> Path:
    out = out_dir / "avatar.png"
    _shot(chrome, AVATAR.format(fonts=_fonts(), palette=_palette(palette_name), letter=letter), out, 640, 640)
    return out


def render(chrome: str, name: str, kicker: str, title: str, sub: str,
           palette_name: str = PALETTE, out_dir: Path = OUT) -> Path:
    palette = _palette(palette_name)
    title_html = re.sub(r"\*(.+?)\*", r"<i>\1</i>", html.escape(title))
    page = PAGE.format(fonts=_fonts(), palette=palette, w=W, h=H, kicker=html.escape(kicker),
                       title=title_html, sub=html.escape(sub))
    out = out_dir / f"{name}.png"
    _shot(chrome, page, out, W, H)
    return out


def main() -> None:
    palette_name = sys.argv[1] if len(sys.argv) > 1 else PALETTE
    if palette_name not in PALETTES:
        raise SystemExit(f"Нет палитры «{palette_name}». Есть: {', '.join(PALETTES)}")
    chrome = find_shooter()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (kicker, title, sub) in BANNERS.items():
        out = render(chrome, name, kicker, title, sub, palette_name)
        print(f"✓ {out.relative_to(HERE.parent)}")
    print(f"✓ {render_avatar(chrome, OUT, palette_name).relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
