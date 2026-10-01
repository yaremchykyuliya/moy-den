"""Баннеры для экранов бота — дизайн «Журнал»: двойная рамка, заголовок по центру.

Запуск: python guides/banners.py  →  products/banners/*.png
         python guides/banners.py latte  →  те же баннеры в другой палитре
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
PALETTE = "chrome"

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
.frame{{position:absolute;inset:34px;border:1.5px solid var(--green);opacity:.55}}
.frame2{{position:absolute;inset:44px;border:1px solid var(--green);opacity:.25}}
.top,.bot{{position:absolute;left:0;right:0;text-align:center}}
.top{{top:84px;font:700 19px 'Manrope',sans-serif;letter-spacing:.34em;text-transform:uppercase;color:var(--green)}}
.bot{{bottom:84px;font:500 24px 'Manrope',sans-serif;letter-spacing:.12em;color:var(--ink-soft)}}
.rule{{position:absolute;left:50%;width:90px;margin-left:-45px;height:1.5px;background:var(--green)}}
h1{{position:absolute;left:200px;right:200px;top:50%;transform:translateY(-54%);text-align:center;
   font:600 104px/1.0 'Cormorant Garamond',Georgia,serif;color:var(--ink);letter-spacing:-.01em;
   font-variant-numeric:lining-nums}}
h1 i{{font-style:italic;font-weight:500;color:var(--green-deep)}}
</style></head><body>
<div class="frame"></div><div class="frame2"></div>
<div class="top">{kicker}</div><div class="rule" style="top:124px"></div>
<h1>{title}</h1>
<div class="rule" style="bottom:132px"></div><div class="bot">{sub}</div>
</body></html>"""


AVATAR = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{fonts}
:root{{{palette}}}
html,body{{margin:0;width:640px;height:640px;overflow:hidden;background:var(--paper)}}
.r1,.r2{{position:absolute;border-radius:50%;border:solid var(--green)}}
.r1{{inset:46px;border-width:3px;opacity:.55}}.r2{{inset:64px;border-width:2px;opacity:.25}}
.l{{position:absolute;left:0;right:0;top:146px;text-align:center;font:italic 500 330px/1 'Cormorant Garamond',Georgia,serif;color:var(--green-deep)}}
</style></head><body><div class="r1"></div><div class="r2"></div><div class="l">{letter}</div></body></html>"""


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
