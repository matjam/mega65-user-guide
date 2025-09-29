#!/usr/bin/env python3
import re
import sys
from pathlib import Path

INPUT_RE = re.compile(r"^\\(input|include)\{([^}]+)\}")

visited = set()

def flatten(path: Path, base: Path, out_lines):
    if path in visited:
        return
    visited.add(path)
    try:
        text = path.read_text(encoding='utf-8')
    except Exception as e:
        sys.stderr.write(f"Warning: cannot read {path}: {e}\n")
        return
    for line in text.splitlines():
        m = INPUT_RE.match(line.strip())
        if m:
            name = m.group(2)
            inc = (base / (name if name.endswith('.tex') else name + '.tex')).resolve()
            if not inc.exists():
                # write the original line if missing
                out_lines.append(line)
            else:
                flatten(inc, inc.parent, out_lines)
        else:
            out_lines.append(line)

def main():
    if len(sys.argv) != 3:
        print("Usage: flatten_tex.py <input.tex> <output.tex>")
        sys.exit(2)
    src = Path(sys.argv[1]).resolve()
    dst = Path(sys.argv[2]).resolve()
    out_lines = []
    flatten(src, src.parent, out_lines)
    text = "\n".join(out_lines) + "\n"
    # Keep only the document body to reduce pandoc parsing issues
    m = re.search(r"\\begin\{document\}(.*)\\end\{document\}", text, flags=re.DOTALL)
    if m:
        body = m.group(1)
    else:
        body = text
    dst.write_text(body, encoding='utf-8')

if __name__ == '__main__':
    main()


