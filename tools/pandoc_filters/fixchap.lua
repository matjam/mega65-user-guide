-- Convert literal LaTeX \chapter{...} RawBlocks into real Header(1) nodes
-- This helps when Pandoc fails to parse chapter commands due to surrounding raw content.

local function parse_label(s)
  if not s then return nil end
  return s:match("\\label%{([^}]+)%}")
end

local function parse_chapter_title(s)
  if not s then return nil end
  return s:match("^%s*\\chapter%s*%{(.-)%}%s*$")
end

local function parse_section_title(s)
  if not s then return nil end
  return s:match("^%s*\\section%s*%{(.-)%}%s*$")
end

local function make_header_from_title(title)
  local inlines = { pandoc.Str(title) }
  local ok, doc = pcall(pandoc.read, title, 'latex')
  if ok and doc and #doc.blocks > 0 and doc.blocks[1].t == 'Para' then
    inlines = doc.blocks[1].c
  end
  return pandoc.Header(1, inlines)
end

function Blocks(blocks)
  local out = {}
  local i = 1
  while i <= #blocks do
    local b = blocks[i]
    if b.t == 'RawBlock' and b.format == 'latex' then
      -- Promote leaked section for Modes into a proper Header(2) so chunking creates its own page
      local sect = parse_section_title(b.text)
      if sect and sect:find("C64, C65 and MEGA65 Modes", 1, true) then
        local inl = { pandoc.Str(sect) }
        local ok, doc = pcall(pandoc.read, sect, 'latex')
        if ok and doc and #doc.blocks > 0 and doc.blocks[1].t == 'Para' then
          inl = doc.blocks[1].c
        end
        table.insert(out, pandoc.Header(2, inl, pandoc.Attr('modes')))
        i = i + 1
        goto continue
      end
      -- If Modes \section appears inside a larger RawBlock, split and emit Header(2)
      local t = b.text
      local s, e, title = t:find('\n?\\section%s*%{(C64, C65 and MEGA65 Modes)%}')
      if s then
        local pre = t:sub(1, s - 1)
        if #pre > 0 then
          table.insert(out, pandoc.RawBlock('latex', pre))
        end
        local inl = { pandoc.Str(title) }
        local ok, doc = pcall(pandoc.read, title, 'latex')
        if ok and doc and #doc.blocks > 0 and doc.blocks[1].t == 'Para' then
          inl = doc.blocks[1].c
        end
        table.insert(out, pandoc.Header(2, inl, pandoc.Attr('modes')))
        local rest = t:sub(e + 1)
        -- consume optional immediate \label{...}
        local lab = rest:match('^%s*\\label%{([^}]+)%}')
        if lab then
          table.insert(out, pandoc.RawBlock('html', '<span id="' .. lab .. '"></span>'))
          rest = rest:gsub('^%s*\\label%{[^}]+%}%s*', '', 1)
        end
        if #rest > 0 then
          table.insert(out, pandoc.RawBlock('latex', rest))
        end
        i = i + 1
        goto continue
      end
      -- Case A: whole block is just a chapter line
      local title = parse_chapter_title(b.text)
      if title then
        local attr = pandoc.Attr()
        if i + 1 <= #blocks then
          local n = blocks[i+1]
          if n.t == 'RawBlock' and n.format == 'latex' then
            local lab = parse_label(n.text)
            if lab then
              attr = pandoc.Attr(lab)
              i = i + 1 -- consume the label block
            end
          end
        end
        local hdr = make_header_from_title(title)
        hdr.identifier = attr.identifier
        table.insert(out, hdr)
        else
        -- Case B: chapter appears inside a larger RawBlock; split it out
        local text = b.text
        local consumed = false
        while true do
          local s, e, title = text:find('\\chapter%s*%{(.-)%}')
          if not s then break end
          local pre = text:sub(1, s - 1)
          if #pre > 0 then
            table.insert(out, pandoc.RawBlock('latex', pre))
          end
          local hdr = make_header_from_title(title)
          table.insert(out, hdr)
          -- consume immediate label after chapter, if present
          local rest = text:sub(e + 1)
          local lab = rest:match('^%s*\\label%{([^}]+)%}')
          if lab then
            table.insert(out, pandoc.RawBlock('html', '<span id="' .. lab .. '"></span>'))
            -- remove that label from rest
            rest = rest:gsub('^%s*\\label%{[^}]+%}%s*', '', 1)
          end
          text = rest
          consumed = true
        end
        if consumed then
          if #text > 0 then
            table.insert(out, pandoc.RawBlock('latex', text))
          end
        else
          table.insert(out, b)
        end
      end
    ::continue::
    elseif (b.t == 'Para' or b.t == 'Plain') then
      -- Detect a chapter command leaked as RawInline inside this block
      local title = nil
      local rest_inlines = {}
      for _, inl in ipairs(b.c) do
        if inl.t == 'RawInline' and inl.format == 'latex' then
          local t = parse_chapter_title(inl.text)
          if t then
            title = t
          else
            table.insert(rest_inlines, inl)
          end
        else
          table.insert(rest_inlines, inl)
        end
      end
      if title then
        local hdr = make_header_from_title(title)
        table.insert(out, hdr)
        -- If the remaining inlines have a lone label, move it to an anchor span after header
        if #rest_inlines == 1 and rest_inlines[1].t == 'RawInline' and rest_inlines[1].format == 'latex' then
          local lab = parse_label(rest_inlines[1].text)
          if lab then
            table.insert(out, pandoc.RawBlock('html', '<span id="' .. lab .. '"></span>'))
            rest_inlines = {}
          end
        end
        if #rest_inlines > 0 then
          table.insert(out, pandoc.Para(rest_inlines))
        end
      else
        table.insert(out, b)
      end
    else
      table.insert(out, b)
    end
    i = i + 1
  end
  return out
end


