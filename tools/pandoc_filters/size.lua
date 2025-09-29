-- Convert LaTeX size declarations (\huge, \small) that precede a token
-- into HTML spans with classes 'size-huge' and 'size-small'.
-- We scope the effect to the next inline only.

local pending_size = nil

local function consume_size_marker(el)
  if el.t == 'RawInline' and (el.format == 'latex' or el.format == 'tex') then
    if el.text:match('\\huge') then
      pending_size = 'size-huge'
      return '__REMOVE__'
    elseif el.text:match('\\small') then
      pending_size = 'size-small'
      return '__REMOVE__'
    end
  elseif el.t == 'Str' then
    -- Handle cases where the size and content are in the same string
    local rem = el.text:match('^\\huge%s*(.+)$')
    if rem then
      return pandoc.Span(pandoc.Str(rem), {class = 'size-huge'})
    end
    rem = el.text:match('^\\small%s*(.+)$')
    if rem then
      return pandoc.Span(pandoc.Str(rem), {class = 'size-small'})
    end
    -- Handle isolated markers as a whole token
    if el.text == '\\huge' then
      pending_size = 'size-huge'
      return '__REMOVE__'
    elseif el.text == '\\small' then
      pending_size = 'size-small'
      return '__REMOVE__'
    end
  end
  return nil
end

function Inlines(inlines)
  local out = {}
  for _, el in ipairs(inlines) do
    local consumed = consume_size_marker(el)
    if consumed ~= nil then
      if consumed == '__REMOVE__' then
        -- do nothing (remove marker)
      elseif consumed.t then
        table.insert(out, consumed)
      end
    else
      if pending_size ~= nil then
        -- Wrap next textual inline
        if el.t == 'Str' or el.t == 'Code' or el.t == 'RawInline' then
          table.insert(out, pandoc.Span(el, {class = pending_size}))
          pending_size = nil
        else
          table.insert(out, el)
        end
      else
        table.insert(out, el)
      end
    end
  end
  return out
end

-- Reset pending size at cell/paragraph boundaries
function Para(el)
  pending_size = nil
  return nil
end

function Plain(el)
  pending_size = nil
  return nil
end


