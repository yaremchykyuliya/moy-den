"""Собирает гайды из guides/*.md в красивые PDF в папке products/.

Запуск:  python guides/build.py            — все гайды
         python guides/build.py 01-*.md    — один гайд
"""
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown
import yaml

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "products"
MD_EXT = ["tables", "sane_lists", "smarty"]
MD_CFG = {"smarty": {"substitutions": {"left-double-quote": "«", "right-double-quote": "»"}}}

BOX_LABELS = {
    "prompt": "Скопируй и подставь своё",
    "result": "Что получишь",
    "why": "Почему сработало",
    "check": "Получилось, если",
    "warn": "Важно",
    "note": "",
    "bad": "Было",
    "good": "Стало",
    "author": "",
    "next": "Что дальше",
}

CHROME_CANDIDATES = [
    os.environ.get("CHROME", ""),
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "google-chrome", "chromium", "chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]


def md(text: str) -> str:
    return markdown.markdown(text, extensions=MD_EXT, extension_configs=MD_CFG)


SHORT_WORDS = r"(?<![\w-])([вскоуаиВСКОУАИ]|за|на|до|по|не|от|из|без|для|Не|На|За|До|По|От|Из|Без|Для)"


def nbsp(text: str) -> str:
    """Неразрывный пробел после чисел и коротких предлогов — чтобы они не висели в конце строки."""
    text = re.sub(r"(?<=\d) (?=\S)", "\u00a0", text)
    return re.sub(SHORT_WORDS + r" (?=\S)", "\\1\u00a0", text)


def prompt_html(text: str) -> str:
    text = html.escape(text.strip("\n"))
    text = re.sub(r"\[([^\]]+)\]", r'<span class="slot">\1</span>', text)
    return text.replace("\n", "<br>")


def render_body(source: str) -> str:
    parts, buf, box = [], [], None
    for line in source.splitlines():
        opening = re.match(r"^:::(\w+)\s*(.*)$", line)
        if box is None and opening:
            parts.append(md("\n".join(buf)))
            buf, box = [], (opening.group(1), opening.group(2).strip())
        elif box is not None and line.strip() == ":::":
            kind, label = box
            if kind not in BOX_LABELS:
                raise SystemExit(f"Неизвестный блок :::{kind}")
            label = label or BOX_LABELS[kind]
            inner = prompt_html("\n".join(buf)) if kind == "prompt" else md("\n".join(buf))
            head = f'<div class="label">{html.escape(label)}</div>' if label else ""
            parts.append(f'<div class="box {kind}">{head}<div class="inner">{inner}</div></div>')
            buf, box = [], None
        else:
            buf.append(line)
    if box is not None:
        raise SystemExit(f"Блок :::{box[0]} не закрыт строкой :::")
    parts.append(md("\n".join(buf)))
    return "\n".join(parts)


def build_html(path: Path) -> tuple[str, dict]:
    raw = path.read_text(encoding="utf-8")
    _, front, body = raw.split("---", 2)
    meta = yaml.safe_load(front)
    template = (HERE / "template.html").read_text(encoding="utf-8")
    number = f"{int(meta['number']):02d}" if meta.get("number") else ""
    values = {
        "kicker": html.escape(meta.get("kicker", "Бесплатный гайд")),
        "badge": html.escape(str(meta.get("badge", number))),
        "footer": html.escape(meta.get("footer", f"Гайд {number} · {meta['title']}")).replace('"', "'"),
        "title": nbsp(html.escape(meta["title"])),
        "promise": nbsp(html.escape(meta["promise"])),
        "time": html.escape(meta["time"]),
        "for": html.escape(meta["for"]),
        "date": html.escape(str(meta["date"])),
        "fonts": (HERE / "fonts" / "fonts.css").read_text(encoding="utf-8"),
        "body": nbsp(render_body(body)),
    }
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template, meta


def find_chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if candidate and (Path(candidate).is_file() or shutil.which(candidate)):
            return shutil.which(candidate) or candidate
    raise SystemExit("Не нашёл Chrome/Chromium. Укажи путь: CHROME=/путь/к/chrome python guides/build.py")


def to_pdf(chrome: str, html_text: str, out: Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".html", dir=HERE, delete=False, encoding="utf-8") as f:
        f.write(html_text)
        tmp = Path(f.name)
    try:
        subprocess.run(
            [chrome, "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
             "--virtual-time-budget=5000", f"--print-to-pdf={out}", tmp.as_uri()],
            check=True, capture_output=True,
        )
    finally:
        tmp.unlink()


def main() -> None:
    patterns = sys.argv[1:] or ["[0-9]*.md", "paid/*.md"]
    files = sorted({p for pattern in patterns for p in HERE.glob(pattern)})
    if not files:
        raise SystemExit("Не нашёл гайдов для сборки")
    chrome = find_chrome()
    OUT.mkdir(exist_ok=True)
    for path in files:
        html_text, meta = build_html(path)
        out = OUT / meta["file"]
        out.parent.mkdir(parents=True, exist_ok=True)
        to_pdf(chrome, html_text, out)
        print(f"✓ {path.relative_to(HERE)} → {out.relative_to(OUT.parent)}")


if __name__ == "__main__":
    main()
