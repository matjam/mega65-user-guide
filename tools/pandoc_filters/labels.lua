-- Inject anchors for LaTeX \label{...} so we can link to them later

local function extract_label(s)
  if not s then return nil end
  return s:match("\\label%{([^}]+)%}")
end

function RawInline(el)
  if el.format == 'latex' then
    local lab = extract_label(el.text)
    if lab then
      return pandoc.Span({}, { id = lab })
    end
  end
  return nil
end

function RawBlock(el)
  if el.format == 'latex' then
    local lab = extract_label(el.text)
    if lab then
      return pandoc.RawBlock('html', '<span id="' .. lab .. '"></span>')
    end
  end
  return nil
end


