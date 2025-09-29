#!/usr/bin/env python3
import re
import sys
from pathlib import Path
import os

BEGIN_DOC = re.compile(r"\\begin\{document\}", re.I)
END_DOC = re.compile(r"\\end\{document\}", re.I)

# Environments that frequently cause pandoc parse failures in complex LaTeX
# Keep simple 'tabular' so pandoc can parse it; drop complex ones
ENV_NAMES = ["longtable", "tabular*", "tabularx", "adjustbox", "tikzpicture"]

# Robustly match environment names without greed or ambiguity
# Allow optional whitespace inside braces; disallow braces/whitespace inside the name
BEGIN_RE = re.compile(r"\\begin\s*\{\s*([^{}\s]+)\s*\}")
END_RE = re.compile(r"\\end\s*\{\s*([^{}\s]+)\s*\}")

def extract_body(text: str) -> str:
    start = BEGIN_DOC.search(text)
    end = END_DOC.search(text)
    if start and end and end.start() > start.end():
        return text[start.end():end.start()]
    return text

def _remove_env_blocks(text: str, env_names, predicate=None) -> str:
    i = 0
    out = []
    n = len(text)
    while i < n:
        mb = BEGIN_RE.search(text, i)
        if not mb:
            out.append(text[i:])
            break
        # copy through before begin
        out.append(text[i:mb.start()])
        env = mb.group(1)
        # find matching end with nesting
        j = mb.end()
        depth = 1
        while j < n and depth > 0:
            nb = BEGIN_RE.search(text, j)
            ne = END_RE.search(text, j)
            if not ne:
                # unmatched, give up and append rest
                out.append(text[mb.start():])
                return "".join(out)
            if nb and nb.start() < ne.start():
                # nested begin
                if nb.group(1) == env:
                    depth += 1
                j = nb.end()
                continue
            # end
            if ne.group(1) == env:
                depth -= 1
            j = ne.end()
        block = text[mb.start():j]
        content = text[mb.end():ne.start()] if depth == 0 else ""
        drop = False
        if env in env_names:
            drop = True
        # If a center contains a table-like env, drop it too
        if env == "center":
            for name in env_names:
                if f"\\begin{{{name}}}" in content:
                    drop = True
                    break
        if predicate and predicate(env, content):
            drop = True
        if drop:
            out.append("\n")
        else:
            out.append(block)
        i = j
    return "".join(out)

def strip_problem_envs(text: str) -> str:
    cleaned = _remove_env_blocks(text, ENV_NAMES)
    # Also drop problematic center blocks containing table markers, if any remain
    cleaned = _remove_env_blocks(cleaned, [], predicate=lambda env, content: env == "center" and (
        "\\begin{longtable}" in content or "\\begin{tabularx}" in content or "\\multicolumn" in content or "\\cellcolor" in content
    ))
    # Drop complex tabulars we can't render yet
    cleaned = _remove_env_blocks(cleaned, [], predicate=lambda env, content: env == "tabular" and (
        "\\multicolumn" in content or "\\cellcolor" in content or "\\hhline" in content or "\\cline" in content
    ))
    # Remove any stray table-related commands that slipped through
    cleaned = re.sub(r"^\\hline.*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\\hhline.*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\\cline.*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\\multicolumn\{[^}]+\}\{[^}]+\}\{[^}]*\}", "", cleaned)
    cleaned = re.sub(r"\\cellcolor\[[^\]]+\]\{[^}]+\}", "", cleaned)
    return cleaned

def strip_problem_macros(text: str) -> str:
    # Drop entire environments that are purely for formatting
    text = re.sub(r"\\begin\{titlepage\}[\s\S]*?\\end\{titlepage\}", "\n", text)
    text = re.sub(r"\\begin\{minitocfmt\}[\s\S]*?\\end\{minitocfmt\}", "\n", text)

    # Remove formatting commands that confuse pandoc's LaTeX reader
    # Inline-stripping of formatting macros wherever they appear
    inline_patterns = [
        r"\\titleformat\*?\{[^}]*\}[^\n]*",
        r"\\titleclass\{[^}]*\}[^\n]*",
        r"\\newpagestyle\{[^}]*\}[^\n]*",
        r"\\pagecolor\[[^\]]*\]\{[^}]*\}",
        r"\\pagecolor\{[^}]*\}",
        r"\\hypersetup\{[^}]*\}",
        r"\\TOCLevels\{[^}]*\}",
        r"\\setcounter\{tocdepth\}\{[^}]*\}",
        # Remove LaTeX tabular spacing and typeface toggles that don't affect HTML
        r"\\setlength\{\\tabcolsep\}\{[^}]*\}",
        r"\\ttfamily\b",
        # Remove LaTeX size switches that shouldn't affect HTML
        r"\\Large\b",
        r"\\normalsize\b",
        r"\\declaretocfmt\{[^}]*\}[^\n]*",
        r"\\begin\{adjustwidth\}[^\n]*",
        r"\\end\{adjustwidth\}",
    ]
    for pat in inline_patterns:
        text = re.sub(pat, "", text)

    # Drop manual page breaks for HTML output
    text = re.sub(r"\\pagebreak\b", "", text)

    # Resolve conditionals for non-printed builds: prefer the \else branch
    # \ifdefined\printmanual ... \else ... \fi  -> keep else content
    text = re.sub(r"\\ifdefined\\printmanual([\s\S]*?)\\else([\s\S]*?)\\fi", r"\2", text)
    # \ifdefined\printmanual ... \fi  -> drop content (since not printing)
    text = re.sub(r"\\ifdefined\\printmanual([\s\S]*?)\\fi", "", text)

    # Preserve size decorators; conversion handled in HTML post-processing

    # Strip LaTeX index macros that should not appear in HTML
    # Allow for exactly one '{}' pair inside braces
    text = re.sub(r"\\index\{[^{}]*(?:\{\})?[^{}]*\}", "", text)
    text = re.sub(r"\\pageref\{[^{}]*(?:\{\})?[^{}]*\}", "", text)
    text = re.sub(r"\\addtocontents\{[^{}]*(?:\{\})?[^{}]*\}", "", text)
    text = re.sub(r"\{\\protect\}", "", text)
    text = re.sub(r"\\needspace\{[^{}]*(?:\{\})?[^{}]*\}", "", text)
    text = re.sub(r"\\nopagebreak", "", text)

    # Simplify known custom macros where feasible
    # Convert \megabookstart{Title}{Version} to a simple chapter heading
    text = re.sub(r"\\megabookstart\{([^}]*)\}\{[^}]*\}", r"\\chapter{\1}", text)

    # Remove problematic macro definitions completely
    text = re.sub(r"\\newcommand\\titlestreq[\s\S]*?\n\}", "", text)
    text = re.sub(r"\\newcommand\\titlepic[\s\S]*?\n\}", "", text)

    # Drop begin/end markers for certain custom envs but keep body
    text = text.replace("\\begin{mega65thanks}", "")
    text = text.replace("\\end{mega65thanks}", "")

    # Convert custom hyppotrap environment into a subsection header preserving body
    def repl_hyppotrap(m: re.Match) -> str:
        name = m.group(1)
        addr = m.group(2)
        num = m.group(3)
        body = m.group(4)
        header = f"\\subsection{{\\texttt{{{name}}} ({addr}/{num})}}\n"
        return header + body + "\n"

    text = re.sub(
        r"\\begin\{hyppotrap\}\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}([\s\S]*?)\\end\{hyppotrap\}",
        repl_hyppotrap,
        text,
    )

    return text

def strip_tex_line_comments(text: str) -> str:
    # Remove lines that are pure LaTeX comments: optional whitespace then % ... end of line
    # Avoid touching code blocks: we convert screen-like envs to HTML later, but comments here are safe to drop
    return re.sub(r"(?m)^[ \t]*%[^\n]*\n?", "", text)

ARROW_MAP = {
    r"\$\s*\\uparrow\s*\$": "↑",
    r"\$\s*\\downarrow\s*\$": "↓",
    r"\$\s*\\leftarrow\s*\$": "←",
    r"\$\s*\\rightarrow\s*\$": "→",
    r"\\uparrow": "↑",
    r"\\downarrow": "↓",
    r"\\leftarrow": "←",
    r"\\rightarrow": "→",
}

def normalize_arrows(text: str) -> str:
    for pat, rep in ARROW_MAP.items():
        text = re.sub(pat, rep, text)
    # Normalize LaTeX pi to MEGA65GraphicSymbols backslash glyph via graphicsymbol macro
    # Pi handled in Lua filter from math inline; avoid injecting here to prevent duplication
    return text

INCG_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")

KEY_MACRO_MAP = [
    # Defer key rendering to Lua filter (avoid HTML injection/escaping issues)
    (r"\\screentext\{([^}]*)\}", r"\\screentext{\1}"),
    (r"\\specialkey\{([^}]*)\}", r"\\specialkey{\1}"),
    (r"\\megakey\{([^}]*)\}", r"\\megakey{\1}"),
    (r"\\megakeywhite\{([^}]*)\}", r"\\megakeywhite{\1}"),
    (r"\\widekey\{([^}]*)\}", r"\\widekey{\1}"),
    (r"\\graphicsymbol\{([^}]*)\}", r"\\graphicsymbol{\1}"),
    (r"\\megasymbolkey", r"\\megasymbolkey"),
]

def wrap_key_macros(text: str) -> str:
    for pat, repl in KEY_MACRO_MAP:
        text = re.sub(pat, repl, text)
    return text

def strip_missing_images(text: str) -> str:
    cwd = Path.cwd()
    def repl(m: re.Match) -> str:
        raw = m.group(1)
        p = Path(raw)
        # Try as-is
        cand = (cwd / p)
        if cand.exists():
            return m.group(0)
        # Try with common extensions
        exts = [".svg", ".png", ".jpg", ".jpeg", ".pdf"]
        for ext in exts:
            cand = (cwd / (str(p) + ext))
            if cand.exists():
                return "\\includegraphics{" + str(p) + ext + "}"
        # Otherwise drop it
        return ""
    return INCG_RE.sub(repl, text)

TABULAR_BLOCK_RE = re.compile(
    r"\\begin\{tabular\*?\}[^}]*\}([\s\S]*?)\\end\{tabular\*?\}",
    re.MULTILINE,
)

def unwrap_nested_tabular(text: str) -> str:
    # If a tabular contains another tabular, drop the outer wrapper to avoid nested tables
    changed = True
    while changed:
        changed = False
        def _repl(m: re.Match) -> str:
            inner = m.group(1)
            if re.search(r"\\begin\{tabular", inner):
                nonlocal changed
                changed = True
                return inner
            return m.group(0)
        text = TABULAR_BLOCK_RE.sub(_repl, text)
    return text

TAB_ENV_RE = re.compile(
    r"\\begin\{(tabular\*?|tabularx|longtable)\}\{([^}]*)\}([\s\S]*?)\\end\{\\1\}",
    re.MULTILINE,
)

def _convert_rows_to_markdown(rows):
    md_lines = []
    if not rows:
        return ""
    header = rows[0]
    md_lines.append("| " + " | ".join(header) + " |")
    md_lines.append("| " + " | ".join(["---"] * len(header)) + " |")
    for r in rows[1:]:
        md_lines.append("| " + " | ".join(r) + " |")
    return "\n".join(md_lines)

def convert_simple_tables_to_markdown(text: str) -> str:
    def repl(m: re.Match) -> str:
        content = m.group(3)
        # Skip complex tables
        if "\\multicolumn" in content or "\\cellcolor" in content:
            return "\n"
        # Remove \hline and surrounding whitespace
        lines = [ln for ln in content.splitlines() if ln.strip() and not ln.strip().startswith("\\hline")]
        # Join continued lines, then split rows on \\
        body = "\n".join(lines)
        parts = re.split(r"\\\\\s*\n?", body)
        rows = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            # Remove trailing \\ if present
            p = re.sub(r"\\\\$", "", p)
            cols = [c.strip() for c in p.split("&")]
            if cols:
                rows.append(cols)
        return "\n" + _convert_rows_to_markdown(rows) + "\n"
    return TAB_ENV_RE.sub(repl, text)

def drop_remaining_tabular(text: str) -> str:
    # Preserve simple tabular environments for pandoc to parse
    return text

def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
    )

def transform_screen_like_blocks(text: str) -> str:
    # Disabled: rely on Lua filters for screen wrapping to avoid double-handling
    return text

def escape_dollars_in_screen_envs(text: str) -> str:
    # Protect unescaped $ inside screen-like envs so pandoc doesn't enter math mode
    env_re = re.compile(r"\\begin\{(basiccode|screencode|screenoutputlined)\}([\s\S]*?)\\end\{\\1\}", re.DOTALL)
    out = []
    last = 0
    for m in env_re.finditer(text):
        out.append(text[last:m.start()])
        env = m.group(1)
        body = m.group(2)
        body_escaped = re.sub(r"(?<!\\)\$", r"\\$", body)
        out.append(f"\\begin{{{env}}}{body_escaped}\\end{{{env}}}")
        last = m.end()
    out.append(text[last:])
    return "".join(out)

def convert_screen_envs_to_html(text: str) -> str:
    # Convert screen-like envs to raw HTML so Pandoc won't reparse them
    env_re = re.compile(r"\\begin\{(basiccode|screencode|screenoutputlined)\}([\s\S]*?)\\end\{\\1\}", re.DOTALL)
    out = []
    last = 0
    for m in env_re.finditer(text):
        out.append(text[last:m.start()])
        body = m.group(2).rstrip("\n")
        esc = _html_escape(body)
        out.append(f"\n<div class=\"screen\"><pre><code>{esc}</code></pre></div>\n")
        last = m.end()
    out.append(text[last:])
    return "".join(out)

def convert_inline_screen_to_html(text: str) -> str:
    # Handle single-paragraph inline: \begin{env} BODY \end{env}
    inline_re = re.compile(r"\\begin\{(basiccode|screencode|screenoutputlined)\}\s*((?:(?!\\end\{\\1\}).)*)\\end\{\\1\}")
    def repl(m: re.Match) -> str:
        body = m.group(2).rstrip("\n")
        esc = _html_escape(body)
        return f"\n<div class=\"screen\"><pre><code>{esc}</code></pre></div>\n"
    return inline_re.sub(repl, text)

def normalize_headings(text: str) -> str:
    # Ensure chapter/section headings are surrounded by blank lines without splitting nested braces
    # Match the heading command at line start and capture the full braced argument up to the last '}' on the line
    text = re.sub(r"(?m)^[ \t]*\\chapter\s*(\{[^\n]*\})", r"\n\n\\chapter\1\n\n", text)
    text = re.sub(r"(?m)^[ \t]*\\section\s*(\{[^\n]*\})", r"\n\n\\section\1\n\n", text)
    text = re.sub(r"(?m)^[ \t]*\\subsection\s*(\{[^\n]*\})", r"\n\n\\subsection\1\n\n", text)
    return text

def collapse_heading_arguments(text: str) -> str:
    # Collapse newlines within heading arguments for \chapter, \section, \subsection, \subsubsection
    # Iterate commands and process sequentially using search
    def process_cmd(t: str, cmd: str) -> str:
        pos = 0
        while True:
            idx = t.find(f"\\{cmd}", pos)
            if idx == -1:
                break
            brace_idx = t.find("{", idx)
            if brace_idx == -1:
                pos = idx + 1
                continue
            # Parse balanced braces starting from brace_idx
            j = brace_idx + 1
            depth = 1
            while j < len(t) and depth > 0:
                c = t[j]
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                j += 1
            if depth != 0:
                # unbalanced; stop processing this occurrence
                pos = idx + 1
                continue
            # j is position after closing brace
            arg = t[brace_idx + 1:j - 1]
            # collapse internal newlines and excessive whitespace to single spaces
            arg_collapsed = re.sub(r"\s+", " ", arg).strip()
            t = t[:brace_idx + 1] + arg_collapsed + t[j - 1:]
            pos = brace_idx + 1 + len(arg_collapsed) + 1
        return t
    for cmd in ["chapter", "section", "subsection", "subsubsection"]:
        text = process_cmd(text, cmd)
    return text

def split_at_modes_chapter(text: str) -> str:
    # Ensure a blank-line boundary before Modes chapter and let pandoc split there
    # We do not drop content; we just enforce clear separation.
    return re.sub(r"(?m)^\\chapter\{C64, C65 and MEGA65 Modes\}", r"\n\n\\clearpage\n\\chapter{C64, C65 and MEGA65 Modes}", text)

def demote_modes_chapter(text: str) -> str:
    # Demote the specific Modes chapter to a section and demote its internal headings by one level
    start_match = re.search(r"(?m)^\\chapter\{C64, C65 and MEGA65 Modes\}", text)
    if not start_match:
        return text
    start = start_match.start()
    next_match = re.search(r"(?m)^\\chapter\{", text[start+1:])
    end = len(text) if not next_match else (start + 1 + next_match.start())
    block = text[start:end]
    # Replace the chapter line with section (keep this specific heading at section level)
    block = re.sub(r"(?m)^\\chapter\{C64, C65 and MEGA65 Modes\}", r"\\section{C64, C65 and MEGA65 Modes}", block, count=1)
    # Demote other headings inside this block (but not the Modes section itself)
    block = re.sub(r"(?m)^\\section\s*\{(?!C64, C65 and MEGA65 Modes\})", r"\\subsection{", block)
    block = re.sub(r"(?m)^\\subsection\s*\{", r"\\subsubsection{", block)
    return text[:start] + block + text[end:]

def main():
    if len(sys.argv) != 3:
        print("Usage: tex_preprocess_for_pandoc.py <in.tex> <out.tex>")
        sys.exit(2)
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    data = src.read_text(encoding='utf-8')
    body = extract_body(data)
    body = strip_problem_macros(body)
    body = strip_tex_line_comments(body)
    body = normalize_arrows(body)
    # Unwrap nested tabulars (keep inner tables only)
    body = unwrap_nested_tabular(body)
    # Keep simple tabulars for pandoc; still strip problematic envs
    body = strip_problem_envs(body)
    # Normalize spacing around headings so chapters/sections don't merge
    body = normalize_headings(body)
    # Collapse accidental newlines inside heading arguments
    body = collapse_heading_arguments(body)
    # Escape unescaped $ inside screen-like environments; Lua filter will render them
    body = escape_dollars_in_screen_envs(body)
    # Do not convert to HTML here; let Lua filters handle screen envs to avoid breaking LaTeX parsing
    body = strip_missing_images(body)
    body = wrap_key_macros(body)
    # Do not inline-convert screen blocks here; handled by Lua filter
    body = drop_remaining_tabular(body)
    # Force split and demote so Modes becomes its own page as a level-2 section
    body = split_at_modes_chapter(body)
    body = demote_modes_chapter(body)
    # Wrap with a minimal LaTeX skeleton so pandoc recognizes \chapter headers
    wrapped = """\\documentclass{book}
\\begin{document}
""" + body + "\n\\end{document}\n"
    dst.write_text(wrapped, encoding='utf-8')

if __name__ == '__main__':
    main()


