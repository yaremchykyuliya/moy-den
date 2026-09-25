"""Собирает гайды из guides/*.md в красивые PDF в папке products/.

Запуск:  python guides/build.py            — все гайды
         python guides/build.py 01-*.md    — один гайд
"""
import html
import json
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
    "lead": "",
    "does": "Что умеет",
    "try": "Попробуй первым",
}

BOT = os.environ.get("GUIDE_BOT", "usefulclaudebot")

# Палитра выбирается в шапке гайда: palette: olive | peony | sand | mountains
PALETTES = {
    "olive": {  # Олива — как в Mini App «Мой день»
        "paper": "#F6F1E7", "card": "#FFFCF5", "ink": "#38332B", "ink-soft": "#8B8375",
        "green": "#5A6E4C", "green-deep": "#3F4F35", "green-mist": "#E4E8DC", "line": "#E7E0D2",
        "muted": "#A79F90", "shadow": "rgba(88,76,52,.06)", "warn-bg": "#F1E6D6", "warn-edge": "#B98B5E",
        "warn-ink": "#8E6440", "bad-bg": "#EFEAE0", "bad-ink": "#6E675B", "next-label": "#C9D3BC", "next-em": "#DCE5CF",
    },
    "peony": {  # Пион — пудровый крем и винная роза
        "paper": "#F8F0EE", "card": "#FFFAF8", "ink": "#3A2A2E", "ink-soft": "#8E7479",
        "green": "#B0566F", "green-deep": "#7A2E45", "green-mist": "#F3DDE2", "line": "#EDDCDC",
        "muted": "#A98E93", "shadow": "rgba(122,46,69,.07)", "warn-bg": "#F4E6DA", "warn-edge": "#C08A5E",
        "warn-ink": "#8A5A36", "bad-bg": "#F0E6E6", "bad-ink": "#75636A", "next-label": "#E8C3CD", "next-em": "#F6D9E0",
    },
    "sand": {  # Песок и золото — слоновая кость, античное золото, эспрессо
        "paper": "#F5EFE4", "card": "#FFFCF6", "ink": "#2F2A24", "ink-soft": "#857A6B",
        "green": "#8C6A30", "green-deep": "#3E3226", "green-mist": "#EFE4CF", "line": "#E8DDC9",
        "muted": "#A89A84", "shadow": "rgba(62,50,38,.07)", "warn-bg": "#F2E3D3", "warn-edge": "#B7825A",
        "warn-ink": "#855A38", "bad-bg": "#EDE6DA", "bad-ink": "#6F6557", "next-label": "#D9C39A", "next-em": "#EBDDBF",
    },
    "mountains": {  # Горы — туман и глубокий сланец
        "paper": "#EEF1F2", "card": "#FAFBFB", "ink": "#25303A", "ink-soft": "#6F7C87",
        "green": "#3F6275", "green-deep": "#243C4A", "green-mist": "#DCE5EA", "line": "#DDE3E7",
        "muted": "#93A0AA", "shadow": "rgba(36,60,74,.07)", "warn-bg": "#F1E7DA", "warn-edge": "#B98B5E",
        "warn-ink": "#8E6440", "bad-bg": "#E6EAEC", "bad-ink": "#5E6A73", "next-label": "#B9CCD8", "next-em": "#D6E3EB",
    },
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


def palette_css(name: str) -> str:
    if name not in PALETTES:
        raise SystemExit(f"Неизвестная палитра «{name}». Есть: {', '.join(PALETTES)}")
    return "\n".join(f"  --{k}:{v};" for k, v in PALETTES[name].items())


COPY_LABEL = re.compile(r"^(\d{1,3})\s*·\s*(.+)$")


def render_body(source: str, copy_prefix: str | None = None, collected: dict | None = None) -> str:
    """copy_prefix — у пронумерованных запросов появится ссылка «Скопировать» на бота."""
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
            raw = "\n".join(buf).strip("\n")
            inner = prompt_html(raw) if kind == "prompt" else md(raw)
            head = f'<div class="label">{html.escape(label)}</div>' if label else ""
            copy = ""
            numbered = COPY_LABEL.match(label) if kind == "prompt" and copy_prefix else None
            if numbered:
                num = int(numbered.group(1))
                collected[str(num)] = {"title": numbered.group(2).strip(), "text": raw}
                url = f"https://t.me/{BOT}?start={copy_prefix}{num:03d}"
                copy = f'<a class="copy" href="{url}"><i></i>Скопировать</a>'
            parts.append(f'<div class="box {kind}">{head}<div class="inner">{inner}</div>{copy}</div>')
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
    copy_prefix = meta.get("copy_prefix")
    collected: dict = {}
    body_html = nbsp(render_body(body, copy_prefix, collected))
    if copy_prefix:
        meta["_templates"] = {"prefix": copy_prefix, "items": collected}
    values = {
        "palette": palette_css(meta.get("palette", "olive")),
        "bot": BOT,
        "kicker": html.escape(meta.get("kicker", "Бесплатный гайд")),
        "badge": html.escape(str(meta.get("badge", number))),
        "footer": html.escape(meta.get("footer", f"Гайд {number} · {meta['title']}")).replace('"', "'"),
        "title": nbsp(html.escape(meta["title"])),
        "promise": nbsp(html.escape(meta["promise"])),
        "time": html.escape(meta["time"]),
        "for": html.escape(meta["for"]),
        "date": html.escape(str(meta["date"])),
        "fonts": (HERE / "fonts" / "fonts.css").read_text(encoding="utf-8"),
        "body": body_html,
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
        if "_templates" in meta:
            data_file = out.with_suffix(".json")
            data_file.write_text(json.dumps(meta["_templates"], ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  + {len(meta['_templates']['items'])} шаблонов для кнопки «Скопировать» → {data_file.relative_to(OUT.parent)}")
        print(f"✓ {path.relative_to(HERE)} → {out.relative_to(OUT.parent)}")


if __name__ == "__main__":
    main()
