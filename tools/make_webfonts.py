#!/usr/bin/env python3
import sys
from pathlib import Path
from fontTools.ttLib import TTFont
import subprocess

def ttf_to_woff2(src: Path, dst: Path):
    font = TTFont(str(src))
    dst.parent.mkdir(parents=True, exist_ok=True)
    font.flavor = 'woff2'
    font.save(str(dst))

def main():
    # Prefer repaired fonts if present
    root = Path('fonts-repaired') if Path('fonts-repaired').exists() else Path('fonts')
    out = Path('fonts-web')
    out.mkdir(exist_ok=True)

    mapping = {
        'mega80-Regular.ttf': 'Mega-Regular.woff2',
        'mega40-Regular.ttf': 'MegaAlt-Regular.woff2',
        'MEGA65GraphicSymbols.otf': 'MEGA65GraphicSymbols.woff2',
        'MegaGlacial-Regular.otf': 'MegaGlacial-Regular.woff2',
        'MegaGlacial-Bold.otf': 'MegaGlacial-Bold.woff2',
        'MegaGlacial-Italic.otf': 'MegaGlacial-Italic.woff2',
        'Inconsolata-Regular.ttf': 'Inconsolata-Regular.woff2',
        'Inconsolata-Bold.ttf': 'Inconsolata-Bold.woff2',
        'xits-regular.otf': 'xits-regular.woff2',
        'xits-bold.otf': 'xits-bold.woff2',
        'xits-italic.otf': 'xits-italic.woff2',
    }

    for src_name, dst_name in mapping.items():
        src = root / src_name
        if not src.exists():
            continue
        dst = out / dst_name
        try:
            ttf_to_woff2(src, dst)
            print(f"Converted {src} -> {dst}")
        except Exception as e:
            print(f"WARN: {src} -> {dst}: {e}")

if __name__ == '__main__':
    sys.exit(main())


