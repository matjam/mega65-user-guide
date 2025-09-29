#!/usr/bin/env python3
from pathlib import Path
from statistics import mean
from fontTools.ttLib import TTFont, newTable


def compute_x_avg_char_width(tt: TTFont) -> int:
    hmtx = tt['hmtx'].metrics
    widths = [adv for adv, lsb in hmtx.values()]
    if not widths:
        return 500
    return int(round(mean(widths)))


def get_first_last_char(tt: TTFont):
    cmaps = [t for t in tt['cmap'].tables if t.cmap]
    codepoints = set()
    for t in cmaps:
        codepoints.update(t.cmap.keys())
    if not codepoints:
        return (0, 0)
    return (min(codepoints), max(codepoints))


def ensure_os2(tt: TTFont, family: str = 'Mega', vendor: str = 'MEGA'):
    if 'OS/2' in tt:
        return
    os2 = newTable('OS/2')
    os2.version = 4
    os2.xAvgCharWidth = compute_x_avg_char_width(tt)
    os2.usWeightClass = 400
    os2.usWidthClass = 5
    os2.fsType = 0
    # Sub/Superscript metrics (reasonable defaults)
    upm = tt['head'].unitsPerEm
    os2.ySubscriptXSize = int(upm * 0.65)
    os2.ySubscriptYSize = int(upm * 0.60)
    os2.ySubscriptXOffset = 0
    os2.ySubscriptYOffset = int(upm * 0.075)
    os2.ySuperscriptXSize = int(upm * 0.65)
    os2.ySuperscriptYSize = int(upm * 0.60)
    os2.ySuperscriptXOffset = 0
    os2.ySuperscriptYOffset = int(upm * 0.35)
    os2.yStrikeoutSize = max(1, int(upm * 0.05))
    os2.yStrikeoutPosition = int(upm * 0.3)
    os2.sFamilyClass = 0
    os2.panose = b"\x00" * 10
    os2.ulUnicodeRange1 = 0
    os2.ulUnicodeRange2 = 0
    os2.ulUnicodeRange3 = 0
    os2.ulUnicodeRange4 = 0
    os2.achVendID = vendor[:4].ljust(4)
    os2.fsSelection = 0x0040  # REGULAR
    first_cp, last_cp = get_first_last_char(tt)
    os2.usFirstCharIndex = first_cp
    os2.usLastCharIndex = last_cp
    hhea = tt['hhea']
    os2.sTypoAscender = hhea.ascent
    os2.sTypoDescender = hhea.descent
    os2.sTypoLineGap = hhea.lineGap
    os2.usWinAscent = max(hhea.ascent, 0)
    os2.usWinDescent = max(-hhea.descent, 0)
    os2.ulCodePageRange1 = 0
    os2.ulCodePageRange2 = 0
    # v2+ extras
    os2.sxHeight = int(upm * 0.5)
    os2.sCapHeight = int(upm * 0.7)
    os2.usDefaultChar = 0
    os2.usBreakChar = 32
    os2.usMaxContext = 1
    tt['OS/2'] = os2


def repair_font(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    tt = TTFont(str(src), recalcBBoxes=True, recalcTimestamp=True)
    ensure_os2(tt)
    tt.save(str(dst))


def main():
    in_root = Path('fonts')
    out_root = Path('fonts-repaired')
    out_root.mkdir(exist_ok=True)

    inputs = [
        'mega80-Regular.ttf',
        'mega40-Regular.ttf',
        'MEGA65GraphicSymbols.otf',
    ]
    for name in inputs:
        src = in_root / name
        if not src.exists():
            continue
        dst = out_root / name
        try:
            repair_font(src, dst)
            print(f"Repaired {src} -> {dst}")
        except Exception as e:
            print(f"WARN: Could not repair {src}: {e}")


if __name__ == '__main__':
    main()


