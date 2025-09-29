-- Convert custom LaTeX key macros to HTML spans with classes
-- Handles: \specialkey{X}, \megakey{X}, \megakeywhite{X}, \widekey{X},
--          \screentext{X}, \screentextwide{X}, \stw{X}, \graphicsymbol{X}, \megasymbolkey, \symbolfont{X}

local function span_with(classes, text)
  return pandoc.Span({ pandoc.Str(text) }, pandoc.Attr('', classes))
end

local function unescape_latex_text(s)
  if not s or s == '' then return s end
  -- Unescape common LaTeX escaped characters: \$, \%, \#, \&, \_, \{, \}, \\
  -- Lua pattern: match a backslash before any of these and drop the backslash
  s = s:gsub("\\([%$%%#&_{}\\])", "%1")
  return s
end

local function render_macro(name, arg)
  -- Normalize alias
  if name == 'stw' then name = 'screentextwide' end
  -- Unescape LaTeX escapes inside screen text macros so \$ -> $
  if name == 'screentext' or name == 'screentextwide' then
    arg = unescape_latex_text(arg)
  end
  if name == 'specialkey' then
    local top, bot = arg:match('^(.-)\\\\(.*)$')
    if not top then top = arg or '' bot = '' end
    local children = {
      pandoc.Span({ pandoc.Str(top) }, pandoc.Attr('', {'k-top'})),
      pandoc.Span({ pandoc.Str(bot) }, pandoc.Attr('', {'k-bot'}))
    }
    return pandoc.Span(children, pandoc.Attr('', {'key','specialkey'}))
  end
  if name == 'megakey' then return span_with({'key','megakey'}, arg) end
  if name == 'megakeywhite' then return span_with({'key','megakeywhite'}, arg) end
  if name == 'widekey' then return span_with({'key','widekey'}, arg) end
  if name == 'screentext' then return span_with({'screentext'}, arg) end
  if name == 'screentextwide' then return span_with({'screentextwide'}, arg) end
  if name == 'graphicsymbol' then return span_with({'graphicsymbol'}, arg) end
  if name == 'symbolfont' then return span_with({'symbolfont'}, arg) end
  if name == 'megasymbolkey' then return span_with({'megasymbolkey'}, '`') end
  return nil
end

local macro_pattern = '\\(specialkey|megakeywhite|megakey|widekey|screentext|screentextwide|stw|graphicsymbol|symbolfont)%{([^}]*)%}'

local function replace_macros_in_text(text)
  -- Normalize common LaTeX text macros
  text = text:gsub('\\ldots', '…')
  local inlines = {}
  local i = 1
  while i <= #text do
    local s1, e1, name, arg = text:find(macro_pattern, i)
    local s2, e2 = text:find('\\megasymbolkey', i)
    local s3, e3, namep, argp = text:find('\\(specialkey|megakeywhite|megakey|widekey|screentext|screentextwide|stw|graphicsymbol|symbolfont)%(([^)]*)%)', i)

    local s, e, kind = nil, nil, nil
    if s1 and (not s2 or s1 < s2) and (not s3 or s1 < s3) then
      s, e, kind = s1, e1, 'arg'
    elseif s3 and (not s2 or s3 < s2) then
      s, e, kind = s3, e3, 'par'
    elseif s2 then
      s, e, kind = s2, e2, 'mega'
    end

    if not s then
      table.insert(inlines, pandoc.Str(text:sub(i)))
      break
    end

    if s > i then
      table.insert(inlines, pandoc.Str(text:sub(i, s - 1)))
    end

    if kind == 'arg' then
      local node = render_macro(name, arg)
      if node then table.insert(inlines, node) end
    elseif kind == 'par' then
      local node = render_macro(namep, argp)
      if node then table.insert(inlines, node) end
    else -- kind == 'mega'
      table.insert(inlines, span_with({'megasymbolkey'}, '`'))
    end

    i = e + 1
  end
  return inlines
end

local function is_tex_like(fmt)
  return fmt == 'tex' or fmt == 'latex' or fmt == 'context'
end

function RawInline(el)
  if not is_tex_like(el.format) then return nil end
  local t = el.text

  local x
  -- Exact macro
  x = t:match('^\\(specialkey|megakeywhite|megakey|widekey|screentext|screentextwide|stw|graphicsymbol|symbolfont)%{([^}]*)%}$')
  if x then
    local name, arg = t:match('^\\([^%{]+)%{([^}]*)%}$')
    return render_macro(name, arg)
  end

  -- Exact megasymbolkey (no args)
  if t == '\\megasymbolkey' then
    return span_with({'megasymbolkey'}, '`')
  end

  -- Macro embedded in other text
  if t:find('\\') then
    return replace_macros_in_text(t)
  end

  return nil
end

function RawBlock(el)
  if not is_tex_like(el.format) then return nil end
  local t = el.text
  -- Strip leading comment markers to allow inline macros after %
  t = t:gsub('^%s*%%+', '')
  if t:find('\\') then
    -- strip leading LaTeX comment markers in this raw block
    t = t:gsub('^%s*%%+', '')
    return pandoc.Para(replace_macros_in_text(t))
  end
  return nil
end

-- Fallback: Sometimes unknown macros leak as plain text tokens.
-- Convert any occurrences we find inside a single Str inline.
function Str(el)
  local t = el.text
  if t and t:find('\\') then
    return replace_macros_in_text(t)
  end
  return nil
end

-- Process inline arrays piecemeal to catch macros split across tokens
local inline_macro_names = {
  'screentext', 'screentextwide', 'stw', 'specialkey', 'megakeywhite', 'megakey', 'widekey', 'graphicsymbol', 'symbolfont'
}

local function starts_with_any_macro(text)
  local best_name, best_pos, best_open
  for _, name in ipairs(inline_macro_names) do
    local pat1 = '\\' .. name .. '%{'
    local pat2 = '\\' .. name .. '%('
    local s1 = text:find(pat1)
    local s2 = text:find(pat2)
    if s1 and (not best_pos or s1 < best_pos) then
      best_name, best_pos, best_open = name, s1, '{'
    end
    if s2 and (not best_pos or s2 < best_pos) then
      best_name, best_pos, best_open = name, s2, '('
    end
  end
  -- Also support \\megasymbolkey (no arg)
  local s2 = text:find('\\megasymbolkey')
  if s2 and (not best_pos or s2 < best_pos) then
    return 'megasymbolkey', s2, nil
  end
  return best_name, best_pos, best_open
end

local function process_inlines(inlines)
  local out = pandoc.List{};
  local i = 1
  while i <= #inlines do
    local el = inlines[i]
    if el.t == 'Str' then
      local text = el.text
      local name, pos, opener = starts_with_any_macro(text)
      if name and pos then
        -- Emit any leading text
        if pos > 1 then
          out:insert(pandoc.Str(text:sub(1, pos - 1)))
        end

        if name == 'megasymbolkey' then
          out:insert(span_with({'megasymbolkey'}, '`'))
          -- Consume this occurrence from current string
          local after = text:sub(pos + #('\\'..name))
          if #after > 0 then out:insert(pandoc.Str(after)) end
          i = i + 1
          goto continue
        end

        -- Collect argument across following tokens until closing '}' or ')'
        local arg = ''
        local j = i
        local close_ch = '}'
        local open_seq = '\\'..name..'{'
        if opener == '(' then
          close_ch = ')'
          open_seq = '\\'..name..'('
        end
        local kText = text:sub(pos + #open_seq)
        local closed_here = false
        while true do
          local rb = kText:find(close_ch, 1, true)
          if rb then
            arg = arg .. kText:sub(1, rb - 1)
            -- push the span
            out:insert(render_macro(name, arg) or pandoc.Str(''))
            local tail = kText:sub(rb + 1)
            if #tail > 0 then out:insert(pandoc.Str(tail)) end
            i = j + 1
            closed_here = true
            break
          else
            arg = arg .. kText
            j = j + 1
            if j > #inlines then
              -- Unclosed; fall back to raw text
              local open_delim = opener == '(' and '(' or '{'
              out:insert(pandoc.Str('\\'..name..open_delim..arg))
              i = j
              break
            end
            local nxt = inlines[j]
            if nxt.t == 'Space' then
              arg = arg .. ' '
              kText = ''
            elseif nxt.t == 'SoftBreak' or nxt.t == 'LineBreak' then
              arg = arg .. ' '
              kText = ''
            elseif nxt.t == 'Str' then
              kText = nxt.text
            else
              -- Unsupported token; end macro
              local open_delim = opener == '(' and '(' or '{'
              out:insert(pandoc.Str('\\'..name..open_delim..arg))
              i = j
              break
            end
          end
        end
        if closed_here then
          goto continue
        end
      else
        out:insert(el)
        i = i + 1
        goto continue
      end
    elseif el.t == 'RawInline' and is_tex_like(el.format) then
      local repl = replace_macros_in_text(el.text)
      for _, n in ipairs(repl) do out:insert(n) end
      i = i + 1
      goto continue
    elseif el.t == 'Emph' or el.t == 'Strong' or el.t == 'SmallCaps' or el.t == 'Strikeout'
        or el.t == 'Superscript' or el.t == 'Subscript' or el.t == 'Underline'
        or el.t == 'Span' or el.t == 'Quoted' or el.t == 'Cite' or el.t == 'Link' then
      if el.content then
        el.content = process_inlines(el.content)
      end
      out:insert(el)
      i = i + 1
      goto continue
    else
      out:insert(el)
      i = i + 1
      goto continue
    end
    ::continue::
  end
  return out
end

function Para(el)
  el.content = process_inlines(el.content)
  return el
end

function Plain(el)
  el.content = process_inlines(el.content)
  return el
end

-- Render inline math pi as the MEGA65 symbol font backslash glyph
function Math(el)
  if el.mathtype and el.mathtype == 'InlineMath' then
    local t = el.text
    if t then
      -- Normalize whitespace but keep spacing meaningful for output we construct
      local t_no_ws = t:gsub('%s+', '')

      -- Exact simple macros
      if t_no_ws == '\\pi' then
        return span_with({'graphicsymbol'}, '\\')
      elseif t_no_ws == '\\times' then
        return pandoc.Str('×')
      elseif t_no_ws == '\\ne' or t_no_ws == '\\neq' then
        return pandoc.Str('≠')
      end

      -- Single Latin letter in inline math: render as italic/emphasis
      local single = t_no_ws:match('^%a$')
      if single then
        return pandoc.Emph({ pandoc.Str(single) })
      end

      -- Pattern: a \times 10^{b}  =>  a × 10^b (with superscript)
      local a, exp = t_no_ws:match('^([%d%.]+)\\times10%^{(%-?%d+)}$')
      if a and exp then
        return {
          pandoc.Str(a),
          pandoc.Space(),
          pandoc.Str('×10'),
          pandoc.Superscript({ pandoc.Str(exp) })
        }
      end

      -- Generic a \times b  => a × b
      local lhs, rhs = t:match('^(.-)\\times(.-)$')
      if lhs and rhs then
        return { pandoc.Str(lhs), pandoc.Space(), pandoc.Str('×'), pandoc.Space(), pandoc.Str(rhs) }
      end

      -- Pattern: number.identifier => italicize identifier (e.g., 205.something)
      local num, ident = t_no_ws:match('^(%d+)%.([%a][%w_]*)$')
      if num and ident then
        return { pandoc.Str(num .. '.'), pandoc.Emph({ pandoc.Str(ident) }) }
      end
    end
  end
  return nil
end


