#!/usr/bin/env python3
import html
import json
import sys
import re
import subprocess
from pathlib import Path
from bs4 import BeautifulSoup

"""
Post-process chunked HTML output to convert LaTeX \vref{label} occurrences
into HTML links to the appropriate page/section.

Strategy:
- Scan all .html files under the given output directory.
- Build a map of id -> (filename, heading_text) by finding ids on h1..h6.
- For each .html file, replace literal "\\vref{label}" with
  <a href="filename#label">heading_text</a> when resolvable; otherwise with
  <a href="#label">label</a> as a minimal fallback (stays on page if local id appears).
"""

HEADING_RE = re.compile(r"<h([1-6])[^>]*id=\"([^\"]+)\"[^>]*>([\s\S]*?)</h\1>", re.IGNORECASE)
ANY_ID_RE = re.compile(r"<([a-zA-Z0-9]+)([^>]*)\sid=\"([^\"]+)\"[^>]*>", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")

def strip_tags(html: str) -> str:
    # Very simple tag stripper for heading text
    return TAG_RE.sub("", html).strip()

def build_id_map(root: Path):
    id_to_target = {}
    for html_path in sorted(root.glob("*.html")):
        try:
            data = html_path.read_text(encoding="utf-8")
        except Exception:
            continue
        # Collect headings with their positions
        headings = []  # list of (start_index, id, text)
        for m in HEADING_RE.finditer(data):
            start = m.start()
            hid = m.group(2)
            text = strip_tags(m.group(3))
            headings.append((start, hid, text))
            id_to_target[hid] = (html_path.name, text or hid)
        headings.sort(key=lambda t: t[0])
        # Collect any other id-bearing elements, map to nearest previous heading text
        for m in ANY_ID_RE.finditer(data):
            start = m.start()
            eid = m.group(3)
            # Skip if already mapped by a heading
            if eid in id_to_target:
                continue
            # Find nearest previous heading
            heading_text = None
            for (hstart, hid, htext) in reversed(headings):
                if hstart <= start:
                    heading_text = htext
                    break
            id_to_target[eid] = (html_path.name, heading_text or eid)
    return id_to_target

VREF_RE = re.compile(r"\\vref\{([^}]+)\}")
BOOKVREF_RE = re.compile(r"\\bookvref\{([^}]+)\}")
FBOX_INCG_RE = re.compile(r"\\fbox\{\s*\\includegraphics(?:\[([^\]]*)\])?\{([^}]+)\}\s*\}")

def rewrite_file(path: Path, id_map: dict):
    data = path.read_text(encoding="utf-8")
    def repl(m: re.Match) -> str:
        label = m.group(1)
        target = id_map.get(label)
        if target:
            fname, text = target
            return f"<a href=\"{fname}#{label}\">{text}</a>"
        # If not found globally, try local anchor only
        return f"<a href=\"#{label}\">{label}</a>"
    new_data = VREF_RE.sub(repl, data)

    # Convert \bookvref{label} similarly to links
    def repl_book(m: re.Match) -> str:
        label = m.group(1)
        target = id_map.get(label)
        if target:
            fname, text = target
            return f"<a href=\"{fname}#{label}\">{text}</a>"
        return f"<a href=\"#{label}\">{label}</a>"

    new_data = BOOKVREF_RE.sub(repl_book, new_data)

    # Replace literal \fbox{\includegraphics[...]{...}} with an <img>
    def repl_fbox(m: re.Match) -> str:
        opts = m.group(1) or ""
        src = m.group(2)
        style = ""
        if opts:
            wm = re.search(r"width\s*=\s*([0-9.]+)\\linewidth", opts)
            if wm:
                try:
                    pct = float(wm.group(1)) * 100.0
                    style = f" style=\"width:{pct:.0f}%;\""
                except Exception:
                    pass
        return f"<img src=\"{src}\" alt=\"\"{style}>"

    new_data = FBOX_INCG_RE.sub(repl_fbox, new_data)

    # Replace <embed src="...pdf"> with <img src="...png"> after converting
    def convert_pdf_to_png(pdf_rel: str) -> str:
        # Resolve relative to the HTML file's directory
        pdf_path = (path.parent / pdf_rel).resolve()
        png_rel = re.sub(r"\.pdf$", ".png", pdf_rel)
        png_path = (path.parent / png_rel).resolve()
        if png_path.exists():
            return png_rel
        # Ensure output directory exists
        png_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Prefer inkscape for vector -> raster conversion
            subprocess.run([
                'inkscape', '--export-type=png', f'--export-filename={str(png_path)}', str(pdf_path)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if png_path.exists():
                return png_rel
        except Exception:
            pass
        try:
            # Fallback to imagemagick convert
            subprocess.run([
                'convert', '-density', '200', str(pdf_path)+'[0]', '-background', 'white', '-alpha', 'remove', str(png_path)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if png_path.exists():
                return png_rel
        except Exception:
            pass
        # As last resort, leave original
        return pdf_rel

    EMBED_RE = re.compile(r"<embed([^>]*)\s+src=\"([^\"]+\.pdf)\"([^>]*)>\s*</embed>|<embed([^>]*)\s+src=\"([^\"]+\.pdf)\"([^>]*)\s*/>", re.IGNORECASE)
    def repl_embed(m: re.Match) -> str:
        # Combine groups for attrs
        attrs_before = (m.group(1) or '') + (m.group(4) or '')
        pdf_src = m.group(2) or m.group(5)
        attrs_after = (m.group(3) or '') + (m.group(6) or '')
        width_attr = ''
        w = re.search(r"\bwidth=\"([^\"]+)\"", attrs_before + attrs_after)
        if w:
            width_attr = f" width=\"{w.group(1)}\""
        new_src = convert_pdf_to_png(pdf_src)
        if new_src.endswith('.png'):
            return f"<img src=\"{new_src}\" alt=\"\"{width_attr}>"
        return m.group(0)

    new_data = EMBED_RE.sub(repl_embed, new_data)

    # Rewrite local anchors <a href="#label">text</a> to cross-page links if target is on another page
    A_LOCAL_RE = re.compile(r"<a([^>]*)\shref=\"#([^\"]+)\"([^>]*)>([\s\S]*?)</a>", re.IGNORECASE)
    def repl_local_anchor(m: re.Match) -> str:
        attrs_before = m.group(1) or ''
        label = m.group(2)
        attrs_after = m.group(3) or ''
        inner_html = m.group(4)
        target = id_map.get(label)
        if not target:
            return m.group(0)
        fname, text = target
        # If the target is on this same file, keep as-is
        if fname == path.name:
            return m.group(0)
        # Otherwise point to the correct file; if inner text is just the raw label, replace with heading text
        pretty = strip_tags(inner_html).strip()
        display = text if pretty == label or pretty.startswith('sec:') or pretty.startswith('cha:') else inner_html
        return f"<a{attrs_before} href=\"{fname}#{label}\"{attrs_after}>{display}</a>"

    new_data = A_LOCAL_RE.sub(repl_local_anchor, new_data)

    # Replace LaTeX \cdots with mid dots; handle math-wrapped forms too
    new_data = re.sub(r"\$\\cdots\$", "⋯", new_data)
    new_data = re.sub(r"\\\(\\cdots\\\)", "⋯", new_data)
    new_data = re.sub(r"\\cdots", "⋯", new_data)

    # Replace LaTeX trademark and registered symbols with Unicode superscripts
    # Handle both standalone and with {} braces
    new_data = re.sub(r"\\textregistered\s*\{\}?", "<sup>®</sup>", new_data)
    new_data = re.sub(r"\\texttrademark\s*\{\}?", "<sup>™</sup>", new_data)
    # Also handle cases where they appear without braces
    new_data = re.sub(r"\\textregistered\b", "<sup>®</sup>", new_data)
    new_data = re.sub(r"\\texttrademark\b", "<sup>™</sup>", new_data)

    # Replace LaTeX \newline with HTML line breaks
    new_data = re.sub(r"\\newline\s*", "<br />", new_data)

    # Strip LaTeX macros that are not needed in HTML output
    new_data = re.sub(r"\\newpage\s*", "", new_data)
    new_data = re.sub(r"\\vspace\*?\{[^}]*\}\s*", "", new_data)

    # Replace size markers with actual spans now that HTML is emitted
    new_data = re.sub(r"@@SIZEHUGE\{([^}]*)\}", r"<span class=\"size-huge\">\\1</span>", new_data)
    new_data = re.sub(r"@@SIZESMALL\{([^}]*)\}", r"<span class=\"size-small\">\\1</span>", new_data)

    # Strip out \pagenumbering{bychapter} from the front page
    new_data = re.sub(r"\\pagenumbering\{bychapter\}", "", new_data)

    # Fix residual patterns from earlier HTML-escaped injections
    # Case: <code>&lt;span class="size-huge"&gt;</code>CONTENT<code>&lt;/span&gt;</code>
    new_data = re.sub(
        r"<code>&lt;span class=\"size-huge\"&gt;</code>([\s\S]*?)<code>&lt;/span&gt;</code>",
        r"<span class=\"size-huge\">\\1</span>",
        new_data,
        flags=re.IGNORECASE,
    )
    new_data = re.sub(
        r"<code>&lt;span class=\"size-small\"&gt;</code>([\s\S]*?)<code>&lt;/span&gt;</code>",
        r"<span class=\"size-small\">\\1</span>",
        new_data,
        flags=re.IGNORECASE,
    )

    # Case: <code>@@SIZEHUGE</code><span>CONTENT</span>
    new_data = re.sub(
        r"<code>@@SIZEHUGE</code>\s*<span>([\s\S]*?)</span>",
        r"<span class=\"size-huge\">\\1</span>",
        new_data,
        flags=re.IGNORECASE,
    )
    new_data = re.sub(
        r"<code>@@SIZESMALL</code>\s*<span>([\s\S]*?)</span>",
        r"<span class=\"size-small\">\\1</span>",
        new_data,
        flags=re.IGNORECASE,
    )

    # Remove any leftover bare tokens
    new_data = new_data.replace('@@SIZEHUGE', '').replace('@@SIZESMALL', '')

    # Directly convert literal LaTeX size prefixes left in HTML text, e.g., \huge0 or \small128
    # Single char after \huge (e.g., 0/1)
    new_data = re.sub(r"\\huge\s*([0-9A-Za-z])", r"<span class=\"size-huge\">\\1</span>", new_data)
    # One or more digits/letters after \small
    new_data = re.sub(r"\\small\s*([0-9A-Za-z]+)", r"<span class=\"size-small\">\\1</span>", new_data)

    # Unescape \$ inside rendered screen code blocks only
    # Matches: <div class="screen"><pre><code> ... </code></pre></div>
    SCREEN_CODE_BLOCK_RE = re.compile(r"(<div class=\"screen\">\s*<pre><code>)(.*?)(</code></pre></div>)", re.DOTALL)
    def repl_unescape_dollar(m: re.Match) -> str:
        head, body, tail = m.group(1), m.group(2), m.group(3)
        body = body.replace("\\$", "$")
        return head + body + tail
    new_data = SCREEN_CODE_BLOCK_RE.sub(repl_unescape_dollar, new_data)

    # Convert \screenshotwrap{path} to centered <img>
    SCREENSHOT_RE = re.compile(r"\\screenshotwrap\{([^}]+)\}")
    def repl_screenshot(m: re.Match) -> str:
      raw = m.group(1)
      src = raw
      # If no extension, try common ones relative to this HTML file
      if not re.search(r"\.[A-Za-z0-9]{3,4}$", src):
        for ext in ('.png', '.jpg', '.jpeg', '.svg'):
          candidate = (path.parent / (src + ext)).resolve()
          if candidate.exists():
            src = src + ext
            break
      return f"<div class=\"screenshotwrap\"><img src=\"{src}\" alt=\"\" style=\"display:block;margin:0 auto;max-width:80%\"></div>"

    new_data = SCREENSHOT_RE.sub(repl_screenshot, new_data)

    # Fix <img src> without extension by probing repo images/ for common extensions
    IMG_TAG_RE = re.compile(r"(<img\s+[^>]*?src=\")(images/[^\"\.]+)(\"[^>]*?>)")
    def repl_img_src(m: re.Match) -> str:
        head, src, tail = m.group(1), m.group(2), m.group(3)
        # if already has extension, keep
        if re.search(r"\.[A-Za-z0-9]{3,4}$", src):
            return m.group(0)
        for ext in ('.png', '.jpg', '.jpeg', '.svg'):
            candidate = (Path.cwd() / (src + ext)).resolve()
            if candidate.exists():
                return f"{head}{src}{ext}{tail}"
        return m.group(0)
    new_data = IMG_TAG_RE.sub(repl_img_src, new_data)

    # Convert paragraphs that contain only a LaTeX begin/end screencode/basiccode
    # into proper HTML code blocks. This catches inline single-paragraph cases
    # that bypassed Lua filters.
    CODE_PARA_RE = re.compile(
        r'<p>\s*\\begin\{(basiccode|screencode|screenoutputlined)\}\s*((?:(?!\\end\{\1\}).)*)\\end\{\1\}\s*</p>',
        re.DOTALL
    )

    def repl_code_para(m: re.Match) -> str:
        body = m.group(2)
        return f"<div class=\"screen\"><pre><code>{body}</code></pre></div>"

    new_data = CODE_PARA_RE.sub(repl_code_para, new_data)

    # Final fallback: replace any stray LaTeX screen env begin/end anywhere in HTML text
    def html_escape(s: str) -> str:
        return (
            s.replace('&', '&amp;')
             .replace('<', '&lt;')
             .replace('>', '&gt;')
        )
    GENERIC_CODE_RE = re.compile(r"\\begin\{(basiccode|screencode|screenoutputlined)\}\s*([\s\S]*?)\\end\{\1\}")
    def repl_generic_code(m: re.Match) -> str:
        body = m.group(2).strip('\n')
        return f"<div class=\"screen\"><pre><code>{html_escape(body)}</code></pre></div>"
    new_data = GENERIC_CODE_RE.sub(repl_generic_code, new_data)

    # Fallback: convert literal tcolorbox with verbatim/lstlisting to screen code blocks
    TCB_VERB_RE = re.compile(r"\\begin\{tcolorbox\}[\s\S]*?\\begin\{verbatim\}\s*([\s\S]*?)\s*\\end\{verbatim\}[\s\S]*?\\end\{tcolorbox\}")
    TCB_LIST_RE = re.compile(r"\\begin\{tcolorbox\}[\s\S]*?\\begin\{lstlisting\}[^\n]*\n?([\s\S]*?)\n?\\end\{lstlisting\}[\s\S]*?\\end\{tcolorbox\}")
    def repl_tcb(m: re.Match) -> str:
        body = m.group(1)
        return f"<div class=\"screen\"><pre><code>{html_escape(body)}</code></pre></div>"
    new_data = TCB_VERB_RE.sub(repl_tcb, new_data)
    new_data = TCB_LIST_RE.sub(repl_tcb, new_data)

    # Fallback: convert literal \screentext{...} and \screentextwide{...} in HTML text to spans
    def replace_inline_screen(text: str) -> str:
        def unescape_latex(s: str) -> str:
            return re.sub(r"\\([\$%#&_{}\\])", r"\1", s)
        def repl_span(cls: str):
            def _r(m: re.Match) -> str:
                body = m.group(1)
                body = unescape_latex(body)
                return f"<span class=\"{cls}\">{body}</span>"
            return _r
        text = re.sub(r"\\screentextwide\{([^}]*)\}", repl_span('screentextwide'), text)
        text = re.sub(r"\\stw\{([^}]*)\}", repl_span('screentextwide'), text)
        text = re.sub(r"\\stw\(([^)]*)\)", repl_span('screentextwide'), text)
        text = re.sub(r"\\screentext\{([^}]*)\}", repl_span('screentext'), text)
        text = re.sub(r"\\symbolfont\{([^}]*)\}", repl_span('symbolfont'), text)
        return text
    new_data = replace_inline_screen(new_data)
    # Also replace any stray \ldots that leaked into HTML text
    new_data = new_data.replace("\\ldots", "…")

    # Fallback: convert leaked key macros (specialkey/megakey/megakeywhite/widekey)
    def replace_key_macros(text: str) -> str:
        def repl_specialkey(m: re.Match) -> str:
            body = m.group(1)
            body = body.replace("\\$", "$")
            parts = body.split("\\\\", 1)
            top = parts[0]
            bot = parts[1] if len(parts) > 1 else ''
            return (
                '<span class="key specialkey">'
                f'<span class="k-top">{top}</span>'
                f'<span class="k-bot">{bot}</span>'
                '</span>'
            )
        def repl_simple(cls: str):
            def _r(m: re.Match) -> str:
                body = m.group(1)
                body = body.replace("\\$", "$")
                return f'<span class="key {cls}">{body}</span>'
            return _r
        text = re.sub(r"\\specialkey\{([^}]*)\}", repl_specialkey, text)
        text = re.sub(r"\\megakey\{([^}]*)\}", repl_simple('megakey'), text)
        text = re.sub(r"\\megakeywhite\{([^}]*)\}", repl_simple('megakeywhite'), text)
        text = re.sub(r"\\widekey\{([^}]*)\}", repl_simple('widekey'), text)
        return text
    new_data = replace_key_macros(new_data)

    # Merge paragraphs where the first paragraph is only a screen span
    # <p><span class="screentextwide">X</span></p><p>rest...</p> => <p><span ...>X</span> rest...</p>
    MERGE_SCREEN_P_RE = re.compile(
        r"<p>\s*(<span[^>]*class=\"(?:screentext|screentextwide)\"[^>]*>[^<]*</span>)\s*</p>\s*<p>([\s\S]*?)</p>",
        re.IGNORECASE
    )
    def repl_merge_p(m: re.Match) -> str:
        span = m.group(1)
        tail = m.group(2)
        return f"<p>{span} {tail}</p>"
    new_data = MERGE_SCREEN_P_RE.sub(repl_merge_p, new_data)

    # Merge paragraphs where the first paragraph ends with a screen span and the next begins with text
    MERGE_ENDSPAN_RE = re.compile(
        r"(<p>[\s\S]*?<span[^>]*class=\"(?:screentext|screentextwide)\"[^>]*>[^<]*</span>)\s*</p>\s*<p>\s*([\s\S]*?)</p>",
        re.IGNORECASE
    )
    def repl_merge_endspan(m: re.Match) -> str:
        head = m.group(1)
        tail = m.group(2)
        return f"{head} {tail}</p>"
    new_data = MERGE_ENDSPAN_RE.sub(repl_merge_endspan, new_data)

    # Merge a preceding text paragraph with a following paragraph that begins with screen span
    MERGE_PREV_TEXT_WITH_SPAN_RE = re.compile(
        r"<p>([\s\S]*?)</p>\s*<p>\s*((?:<span[^>]*class=\"(?:screentext|screentextwide)\"[^>]*>[^<]*</span>[\s\S]*?))</p>",
        re.IGNORECASE
    )
    def repl_merge_prev_span(m: re.Match) -> str:
        prev = m.group(1).rstrip()
        nextp = m.group(2).lstrip()
        return f"<p>{prev} {nextp}</p>"
    new_data = MERGE_PREV_TEXT_WITH_SPAN_RE.sub(repl_merge_prev_span, new_data)

    # Convert LaTeX-style emphasis groups {\em ...} to <em>...</em> (supports multi-line)
    def repl_emphasis(m: re.Match) -> str:
        body = m.group(1)
        return f"<em>{body}</em>"
    new_data = re.sub(r"\{\s*\\em\s+([\s\S]*?)\}", repl_emphasis, new_data)

    # Safety: drop any literal LaTeX chapter that leaked into this chunk (prevents cross-chapter bleed)
    new_data = re.sub(r"\n\\chapter\{[^}]+\}[\s\S]*$", "\n", new_data)

    # Special hack: enrich the landing page with front cover image and the MEGA65 TEAM + updates blocks
    if path.name == '1-mega65-reference-guide.html':
        def render_team_from_regulatory() -> str:
            try:
                reg = Path('regulatory.tex').read_text(encoding='utf-8')
            except Exception:
                return ''
            # Extract all minipage blocks
            entries = []
            for m in re.finditer(r"\\begin\{minipage\}\{[^}]*\}([\s\S]*?)\\end\{minipage\}", reg):
                blk = m.group(1)
                name_m = re.search(r"\{\\large\\bf\s+([^}]+)\}", blk)
                nick_m = re.search(r"\\textit\{\(([^)]+)\)\}", blk)
                # Roles: collect remaining non-empty lines that are not name or nick
                roles = []
                for line in blk.splitlines():
                    line = line.strip()
                    if not line or line.startswith('{\\large') or line.startswith('\\textit'):
                        continue
                    # strip trailing \\ and TeX braces
                    line = re.sub(r"\\\\$", "", line)
                    line = line.strip()
                    if line:
                        roles.append(line)
                name = name_m.group(1).strip() if name_m else ''
                nick = nick_m.group(1).strip() if nick_m else ''
                if name or roles:
                    entries.append((name, nick, roles))
            if not entries:
                return ''
            # Build HTML
            parts = ["<h2>MEGA65 TEAM</h2>", '<ul class="team">']
            for name, nick, roles in entries:
                nick_html = f" <em>({nick})</em>" if nick else ''
                role_html = ''
                if roles:
                    role_html = '<div class="roles">' + '; '.join(roles) + '</div>'
                parts.append(f"<li><strong>{name}</strong>{nick_html}{role_html}</li>")
            parts.append('</ul>')
            return "\n".join(parts)

        cover_html = (
            '<div class="frontcover" style="text-align:center;margin:1rem 0;">'
            '<img src="frontcover/m65book_title.png" alt="MEGA65 front cover" '
            'style="max-width:100%;height:auto;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,.2)"></div>'
        )
        # Render regulatory.tex and updates.tex in a very lightweight way by inlining their important parts
        # We only inject once, near the top after the main <h1>
        def inject_after_h1(html: str, snippet: str) -> str:
            return re.sub(r"(</h1>)", r"\\1\n" + re.escape(snippet), html, count=1)
        # Build MEGA65 TEAM section header
        team_rendered = render_team_from_regulatory() or '<h2>MEGA65 TEAM</h2>'
        # Insert cover below the site nav (<nav id="sitenav">...</nav>)
        if re.search(r"</nav>", new_data, flags=re.IGNORECASE):
            new_data = re.sub(r"</nav>", r"</nav>\n" + cover_html, new_data, count=1, flags=re.IGNORECASE)
        else:
            new_data = re.sub(r"(<body[^>]*>)", r"\1\n" + cover_html, new_data, count=1, flags=re.IGNORECASE)

        # Build git info snippet from gitinfo.tex
        def render_gitinfo_html() -> str:
            try:
                gi = Path('gitinfo.tex').read_text(encoding='utf-8')
            except Exception:
                return ''
            # Extract commit and date lines, ignoring LaTeX environment markers
            commit_match = re.search(r"commit\s+([0-9a-f]{7,40})", gi, flags=re.IGNORECASE)
            date_match = re.search(r"date:\s*([^\n\\]+)", gi, flags=re.IGNORECASE)
            if not commit_match or not date_match:
                return ''
            sha = commit_match.group(1)
            date = date_match.group(1).strip()
            return f"<div class=\"screen\"><pre><code>commit {sha}\ndate: {date}</code></pre></div>"

        gitinfo_html = render_gitinfo_html()

        # Expand Reporting section with full language from updates.tex and append git info and bold notice
        updates_full = (
            '<h2>Reporting Errors and Omissions</h2>'
            '<p>This book is being continuously refined and improved upon by the MEGA65 community.</p>'
            '<p>The version of this edition is:</p>'
            f'{gitinfo_html}'
            '<p>We want this book to be the best that it possibly can. '
            'So if you see any errors, find anything that is missing, or would like more information, '
            'please report them using the MEGA65 User\'s Guide issue tracker:</p>'
            '<p><a href="https://github.com/mega65/mega65-user-guide/issues">https://github.com/mega65/mega65-user-guide/issues</a></p>'
            '<p>You can also check there to see if anyone else has reported a similar problem, '
            'while you wait for this book to be updated.</p>'
            '<p>Finally, you can always download the latest versions of our suite of books from these locations:</p>'
            '<ul>'
            '<li><a href="https://mega65.org/mega65-book">https://mega65.org/mega65-book</a></li>'
            '<li><a href="https://mega65.org/user-guide">https://mega65.org/user-guide</a></li>'
            '<li><a href="https://mega65.org/developer-guide">https://mega65.org/developer-guide</a></li>'
            '<li><a href="https://mega65.org/basic65-ref">https://mega65.org/basic65-ref</a></li>'
            '<li><a href="https://mega65.org/chipset-ref">https://mega65.org/chipset-ref</a></li>'
            '<li><a href="https://mega65.org/docs">https://mega65.org/docs</a></li>'
            '</ul>'
            '<p><strong>This web version of the Mega65 Compendium is generated from the same source as the books, however it may contain '
            'errors or omissions due to the conversion process. You should always consider the PDF and Hard Copy versions of The Mega65 '
            'Book as the official representation. If you find content missing from the Web version of The Mega65 Book, please report an '
            'issue in the issue tracker linked above.</strong></p>'
        )

        # Insert team and updates after first h1 if present, otherwise after cover
        def _repl_h1(m: re.Match) -> str:
            return m.group(0) + "\n" + team_rendered + "\n" + updates_full
        if re.search(r"</h1>", new_data, flags=re.IGNORECASE):
            new_data = re.sub(r"</h1>", _repl_h1, new_data, count=1, flags=re.IGNORECASE)
        else:
            new_data = new_data.replace(cover_html, cover_html + team_rendered + updates_full, 1)

    if new_data != data:
        path.write_text(new_data, encoding="utf-8")

def extract_toc_from_index(outdir: Path) -> str:
    """Extract the TOC from index.html to use in sidebar."""
    index_path = outdir / "index.html"
    if not index_path.exists():
        return ""
    
    try:
        data = index_path.read_text(encoding="utf-8")
        # Find the TOC nav element
        toc_match = re.search(r'<nav id="TOC"[^>]*>(.*?)</nav>', data, re.DOTALL)
        if toc_match:
            return toc_match.group(1)
    except Exception:
        pass
    return ""

def add_sidebar_to_html(html_content: str, toc_content: str, current_file: str) -> str:
    """Add sidebar navigation to HTML content."""
    # Find the body tag and insert sidebar
    body_match = re.search(r'(<body[^>]*>)', html_content)
    if not body_match:
        return html_content
    
    body_start = body_match.end()
    
    # Create sidebar HTML with search bar
    sidebar_html = f'''<div class="sidebar">
    <div class="search-container">
        <input type="text" id="searchInput" placeholder="Search documentation..." class="search-input">
        <div id="searchResults" class="search-results"></div>
    </div>
    <nav id="TOC" role="doc-toc">
    {toc_content}
    </nav>
    </div>
    <div class="main-content">'''
    
    # Insert sidebar after body tag
    new_content = html_content[:body_start] + sidebar_html + html_content[body_start:]
    
    # Close the main-content div before closing body tag
    new_content = re.sub(r'(</body>)', r'</div>\1', new_content)
    
    # Mark current page as active in sidebar
    if current_file != "index.html":
        # Find the link to current file and mark it as active
        current_file_escaped = re.escape(current_file)
        new_content = re.sub(
            rf'(<a[^>]*href="{current_file_escaped}"[^>]*>)',
            r'\1',
            new_content
        )
        # Add active class to the link
        new_content = re.sub(
            rf'(<a[^>]*href="{current_file_escaped}"[^>]*class=")([^"]*)(")',
            r'\1\2 active\3',
            new_content
        )
        # Handle case where there's no existing class
        new_content = re.sub(
            rf'(<a[^>]*href="{current_file_escaped}"[^>]*)(>)',
            r'\1 class="active"\2',
            new_content
        )
    
    return new_content

def rename_colon_files(outdir: Path) -> dict:
    """Rename files with colons in their names and return mapping of old->new names."""
    rename_map = {}
    
    # Find all files with ':' in the name
    colon_files = list(outdir.glob("*:*"))
    
    for old_path in colon_files:
        # Replace all colons with underscores
        new_name = old_path.name.replace(":", "_")
        new_path = old_path.parent / new_name
        
        # Rename the file
        old_path.rename(new_path)
        rename_map[old_path.name] = new_name
        print(f"Renamed: {old_path.name} -> {new_name}")
    
    return rename_map

def update_links_in_html(html_path: Path, rename_map: dict):
    """Update all links in an HTML file to use new filenames."""
    if not rename_map:
        return
    
    try:
        data = html_path.read_text(encoding="utf-8")
        original_data = data
        
        # Update all href attributes that point to renamed files
        for old_name, new_name in rename_map.items():
            # Update href="old_name" to href="new_name"
            data = re.sub(
                rf'href="([^"]*){re.escape(old_name)}"',
                rf'href="\g<1>{new_name}"',
                data
            )
            # Also handle href="old_name" (without path)
            data = re.sub(
                rf'href="{re.escape(old_name)}"',
                rf'href="{new_name}"',
                data
            )
        
        if data != original_data:
            html_path.write_text(data, encoding="utf-8")
            print(f"Updated links in: {html_path.name}")
    
    except Exception as e:
        print(f"Warning: Could not update links in {html_path.name}: {e}")

def create_search_index(outdir: Path) -> None:
    """Create a search index of all HTML pages and save to JSON file."""
    search_data = []
    
    for html_path in sorted(outdir.glob("*.html")):
        try:
            content = html_path.read_text(encoding="utf-8")
            soup = BeautifulSoup(content, 'html.parser')
            
            # Extract title
            title_tag = soup.find('title')
            title = title_tag.get_text().strip() if title_tag else html_path.stem
            
            # Extract main content (skip navigation and sidebar)
            main_content_div = soup.find('div', class_='main-content')
            if main_content_div:
                # Remove script and style elements
                for script in main_content_div(["script", "style"]):
                    script.decompose()
                
                # Get clean text content
                clean_text = main_content_div.get_text()
                # Clean up whitespace
                clean_text = re.sub(r'\s+', ' ', clean_text).strip()
            else:
                # Fallback: extract all text content from body
                body = soup.find('body')
                if body:
                    for script in body(["script", "style", "nav", "aside"]):
                        script.decompose()
                    clean_text = body.get_text()
                    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                else:
                    clean_text = soup.get_text()
                    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
            
            # Remove LaTeX markup - safer approach
            # Remove common LaTeX commands with balanced braces
            clean_text = re.sub(r'\\[a-zA-Z]+\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', '', clean_text)  # \command{content} with balanced braces
            clean_text = re.sub(r'\\[a-zA-Z]+', '', clean_text)  # \command without braces
            clean_text = re.sub(r'\\[^a-zA-Z\s]', '', clean_text)  # \special chars (but not whitespace)
            clean_text = re.sub(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', '', clean_text)  # {content} groups with balanced braces
            clean_text = re.sub(r'\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]', '', clean_text)  # [content] groups with balanced brackets
            clean_text = re.sub(r'\\[a-zA-Z]*', '', clean_text)  # any remaining \commands
            clean_text = re.sub(r'\s+', ' ', clean_text).strip()  # clean up whitespace again
            
            # Extract headings from main content
            headings = []
            if main_content_div:
                for heading in main_content_div.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                    heading_text = heading.get_text().strip()
                    # Remove LaTeX markup from headings too - safer approach
                    heading_text = re.sub(r'\\[a-zA-Z]+\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', '', heading_text)
                    heading_text = re.sub(r'\\[a-zA-Z]+', '', heading_text)
                    heading_text = re.sub(r'\\[^a-zA-Z\s]', '', heading_text)
                    heading_text = re.sub(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', '', heading_text)
                    heading_text = re.sub(r'\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]', '', heading_text)
                    heading_text = re.sub(r'\\[a-zA-Z]*', '', heading_text)
                    heading_text = re.sub(r'\s+', ' ', heading_text).strip()
                    if heading_text:  # Only add non-empty headings
                        headings.append(heading_text)
            else:
                # Fallback: extract all headings
                for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                    heading_text = heading.get_text().strip()
                    # Remove LaTeX markup from headings too - safer approach
                    heading_text = re.sub(r'\\[a-zA-Z]+\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', '', heading_text)
                    heading_text = re.sub(r'\\[a-zA-Z]+', '', heading_text)
                    heading_text = re.sub(r'\\[^a-zA-Z\s]', '', heading_text)
                    heading_text = re.sub(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', '', heading_text)
                    heading_text = re.sub(r'\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]', '', heading_text)
                    heading_text = re.sub(r'\\[a-zA-Z]*', '', heading_text)
                    heading_text = re.sub(r'\s+', ' ', heading_text).strip()
                    if heading_text:  # Only add non-empty headings
                        headings.append(heading_text)
            
            headings_text = ' '.join(headings)
                        
            search_data.append({
                'title': title,
                'url': html_path.name,
                'content': clean_text,
                'headings': headings_text,
                'filename': html_path.stem
            })
            
        except Exception as e:
            print(f"Warning: Could not process {html_path.name} for search index: {e}")
    
    # Write search index to separate JSON file
    search_index_path = outdir / "search-index.json"
    with open(search_index_path, 'w', encoding='utf-8') as f:
        json.dump(search_data, f, ensure_ascii=False, indent=2)
    
    print(f"Search index written to {search_index_path}")

def add_search_script(html_content: str) -> str:
    """Add Fuse.js and search functionality to HTML content."""
    # Find the closing head tag
    head_end_match = re.search(r'(</head>)', html_content)
    if not head_end_match:
        return html_content
    
    head_end = head_end_match.start()
    
    # Add Fuse.js CDN and search script
    search_script = '''
    <script src="https://cdn.jsdelivr.net/npm/fuse.js@6.6.2/dist/fuse.basic.min.js"></script>
    <script>
        // Search functionality
        let searchIndex = null;
        let fuse = null;
        let searchIndexLoaded = false;
        
        // Initialize search when page loads
        document.addEventListener('DOMContentLoaded', function() {
            const searchInput = document.getElementById('searchInput');
            const searchResults = document.getElementById('searchResults');
            
            if (!searchInput || !searchResults) return;
            
            // Load search index on first search
            searchInput.addEventListener('input', function(e) {
                const query = e.target.value.trim();
                
                if (query.length < 2) {
                    searchResults.innerHTML = '';
                    searchResults.style.display = 'none';
                    return;
                }
                
                // Load search index if not already loaded
                if (!searchIndexLoaded) {
                    loadSearchIndex().then(() => {
                        performSearch(query, searchResults);
                    });
                } else {
                    performSearch(query, searchResults);
                }
            });
            
            // Hide results when clicking outside
            document.addEventListener('click', function(e) {
                if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
                    searchResults.style.display = 'none';
                }
            });
        });
        
        async function loadSearchIndex() {
            if (searchIndexLoaded) return;
            
            try {
                const response = await fetch('search-index.json');
                if (!response.ok) {
                    throw new Error('Failed to load search index');
                }
                searchIndex = await response.json();
                
                // Initialize Fuse.js
                fuse = new Fuse(searchIndex, {
                    keys: [ 'title', 'content', 'headings', 'filename' ],
                    threshold: 0.4,  // More lenient threshold (0.0 = exact match, 1.0 = match anything)
                    includeScore: true,
                    includeMatches: true,
                    minMatchCharLength: 2,  // Minimum characters to match
                    findAllMatches: true,   // Find all matches, not just the first
                    distance: 10,
                    ignoreLocation: true
                });
                
                searchIndexLoaded = true;
            } catch (error) {
                console.error('Error loading search index:', error);
                searchIndex = [];
                searchIndexLoaded = true; // Prevent repeated attempts
            }
        }
        
        function performSearch(query, container) {
            if (!fuse) {
                container.innerHTML = '<div class="search-error">Search index not available</div>';
                container.style.display = 'block';
                return;
            }
            
            const results = fuse.search(query);
            displaySearchResults(results, container);
        }
        
        function displaySearchResults(results, container) {
            if (results.length === 0) {
                container.innerHTML = '<div class="search-no-results">No results found</div>';
                container.style.display = 'block';
                return;
            }
            
            let html = '<div class="search-results-list">';
            results.slice(0, 10).forEach(result => {
                const item = result.item;
                const score = result.score;
                const matches = result.matches || [];
                
                // Highlight matched text
                let highlightedTitle = item.title;
                let highlightedContent = item.content.substring(0, 200) + '...';
                
                if (matches.length > 0) {
                    matches.forEach(match => {
                        if (match.key === 'title') {
                            highlightedTitle = highlightText(highlightedTitle, match.indices);
                        } else if (match.key === 'content') {
                            highlightedContent = highlightText(highlightedContent, match.indices);
                        }
                    });
                }
                
                html += `
                    <div class="search-result-item" onclick="window.location.href='${item.url}'">
                        <div class="search-result-title">${highlightedTitle}</div>
                        <div class="search-result-content">${highlightedContent}</div>
                        <div class="search-result-url">${item.filename}</div>
                    </div>
                `;
            });
            html += '</div>';
            
            container.innerHTML = html;
            container.style.display = 'block';
        }
        
        function highlightText(text, indices) {
            if (!indices || indices.length === 0) return text;
            
            let result = '';
            let lastIndex = 0;
            
            indices.forEach(([start, end]) => {
                result += text.substring(lastIndex, start);
                result += `<mark>${text.substring(start, end + 1)}</mark>`;
                lastIndex = end + 1;
            });
            
            result += text.substring(lastIndex);
            return result;
        }
    </script>
    '''
    
    # Insert the script before closing head tag
    new_content = html_content[:head_end] + search_script + html_content[head_end:]
    
    return new_content

def main():
    if len(sys.argv) != 2:
        print("Usage: postprocess_html_refs.py <html_output_dir>")
        sys.exit(2)
    outdir = Path(sys.argv[1])
    if not outdir.is_dir():
        print(f"ERROR: Not a directory: {outdir}")
        sys.exit(1)
    
    # First, rename files with colons in their names
    print("Renaming files with colons in their names...")
    rename_map = rename_colon_files(outdir)
    
    # Extract TOC from index.html
    toc_content = extract_toc_from_index(outdir)
    
    # Create search index
    print("Creating search index...")
    create_search_index(outdir)
    
    id_map = build_id_map(outdir)
    for html_path in sorted(outdir.glob("*.html")):
        # Add sidebar to each HTML file
        if toc_content:
            data = html_path.read_text(encoding="utf-8")
            new_data = add_sidebar_to_html(data, toc_content, html_path.name)
            html_path.write_text(new_data, encoding="utf-8")
        
        # Add search functionality
        data = html_path.read_text(encoding="utf-8")
        new_data = add_search_script(data)
        html_path.write_text(new_data, encoding="utf-8")
        
        # Update links to use new filenames
        update_links_in_html(html_path, rename_map)
        
        rewrite_file(html_path, id_map)

if __name__ == "__main__":
    main()


