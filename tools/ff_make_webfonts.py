#!/usr/bin/env python3
# Generate repaired WOFF2 using FontForge for fonts that fontTools can't handle
import fontforge  # type: ignore
import psMat      # type: ignore
from pathlib import Path

def repair_and_export(src_path: Path, dst_path: Path, family_name: str):
    font = fontforge.open(str(src_path))
    # Ensure names present
    font.familyname = family_name
    if not font.fullname:
        font.fullname = family_name
    if not font.fontname:
        font.fontname = family_name.replace(' ', '')
    # Generate OS/2 if missing; FontForge will synthesize reasonable defaults
    font.os2_version = 4
    font.os2_weight = 400
    font.os2_width = 5
    font.os2_family_class = 0
    # Export WOFF2
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    font.generate(str(dst_path), flags=("round",))
    font.close()

def main():
    in_root = Path('fonts')
    out_root = Path('fonts-web')
    out_root.mkdir(exist_ok=True)

    plan = [
        (in_root / 'mega80-Regular.ttf', out_root / 'Mega-Regular.woff2', 'Mega'),
        (in_root / 'mega40-Regular.ttf', out_root / 'MegaAlt-Regular.woff2', 'MegaAlt'),
    ]
    for src, dst, fam in plan:
        if not src.exists():
            continue
        try:
            repair_and_export(src, dst, fam)
            print(f"FontForge exported {dst}")
        except Exception as e:
            print(f"WARN: FontForge failed for {src}: {e}")

if __name__ == '__main__':
    main()


