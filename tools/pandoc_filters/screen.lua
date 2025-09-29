-- Transform LaTeX screen-like blocks into styled HTML blocks
-- Supported forms:
--  1) tcolorbox containing verbatim or lstlisting
--  2) custom environments: basiccode, screencode, screenoutputlined

local function make_screen_block(code_text)
  -- Undo LaTeX $ escaping so code shows N$ rather than N\$
  code_text = code_text:gsub('\\%$', '$')
  local cb = pandoc.CodeBlock(code_text)
  local div = pandoc.Div({ cb }, pandoc.Attr(nil, { 'screen' }))
  return div
end

local function extract_code_from_tcolorbox(text)
  local body = text:match("\\begin%{verbatim%}\n?(.-)\n?\\end%{verbatim%}")
  if body then return body end
  body = text:match("\\begin%{lstlisting%}[^\n]*\n?(.-)\n?\\end%{lstlisting%}")
  return body
end

function RawBlock(el)
  if el.format ~= 'latex' then return nil end
  local t = el.text

  -- tcolorbox + verbatim
  local verbatim_body = t:match("^\\\\begin%{tcolorbox%}.-\\\\begin%{verbatim%}\n?(.-)\n?\\\\end%{verbatim%}.-\\\\end%{tcolorbox%}$")
  if verbatim_body then
    return make_screen_block(verbatim_body)
  end

  -- tcolorbox + lstlisting
  local listing_body = t:match("^\\\\begin%{tcolorbox%}.-\\\\begin%{lstlisting%}[^\n]*\n?(.-)\n?\\\\end%{lstlisting%}.-\\\\end%{tcolorbox%}$")
  if listing_body then
    return make_screen_block(listing_body)
  end

  -- basiccode environment
  local basic_body = t:match("^\\\\begin%{basiccode%}[^\n]*\n?(.-)\n?\\\\end%{basiccode%}$")
  if basic_body then
    return make_screen_block(basic_body)
  end

  -- screencode environment
  local screen_body = t:match("^\\\\begin%{screencode%}[^\n]*\n?(.-)\n?\\\\end%{screencode%}$")
  if screen_body then
    return make_screen_block(screen_body)
  end

  -- screenoutputlined environment
  local sol_body = t:match("^\\\\begin%{screenoutputlined%}[^\n]*\n?(.-)\n?\\\\end%{screenoutputlined%}$")
  if sol_body then
    return make_screen_block(sol_body)
  end

  return nil
end

-- Handle multi-block environments like basiccode/screencode where pandoc may
-- split begin/end across separate RawBlocks.
function Blocks(blocks)
  local out = pandoc.List:new()
  local i = 1
  while i <= #blocks do
    local b = blocks[i]
    -- Try single-block transforms first
    if b.t == 'RawBlock' then
      local single = RawBlock(b)
      if single then
        out:insert(single)
        i = i + 1
      else
        -- Look for begin{basiccode} or begin{screencode}
        if b.format == 'latex' then
          local bt = b.text
          local env = bt:match("\\\\begin%{(basiccode)%}")
                    or bt:match("\\\\begin%{(screencode)%}")
                    or bt:match("\\\\begin%{(screenoutputlined)%}")
                    or bt:match("\\\\begin%{(tcolorbox)%}")
          if env then
            local code_buf = {}
            -- consume subsequent blocks until we find \end{env}
            i = i + 1
            while i <= #blocks do
              local nb = blocks[i]
              if nb.t == 'RawBlock' and nb.format == 'latex' then
                local txt = nb.text
                local end_pat = "\\\\end%{" .. env .. "%}"
                if txt:match(end_pat) then
                  local pre = txt:gsub(end_pat .. ".*$", "")
                  if #pre > 0 then table.insert(code_buf, pre) end
                  out:insert(make_screen_block(table.concat(code_buf, "\n")))
                  i = i + 1
                  break
                end
                -- If a new begin of a screen env appears before an end, stop to avoid greediness
                if txt:match("\\\\begin%{(basiccode|screencode|screenoutputlined|tcolorbox)%}") then
                  local collected = table.concat(code_buf, "\n")
                  if env == 'tcolorbox' then
                    local body = extract_code_from_tcolorbox(collected)
                    if body then
                      out:insert(make_screen_block(body))
                    else
                      out:insert(nb)
                    end
                  else
                    out:insert(make_screen_block(collected))
                  end
                  -- Do not consume this block; let outer loop handle it
                  break
                end
                table.insert(code_buf, txt)
                i = i + 1
              elseif nb.t == 'CodeBlock' then
                table.insert(code_buf, nb.text)
                i = i + 1
              elseif nb.t == 'Para' or nb.t == 'Plain' then
                local txt = pandoc.utils.stringify(nb)
                table.insert(code_buf, txt)
                i = i + 1
              else
                table.insert(code_buf, pandoc.utils.stringify(nb))
                i = i + 1
              end
            end
          else
            out:insert(b)
            i = i + 1
          end
        else
          out:insert(b)
          i = i + 1
        end
      end
    elseif b.t == 'Para' or b.t == 'Plain' then
      -- Detect inline begin{env} in a paragraph/plain and collect until matching end
      local t = pandoc.utils.stringify(b)
          local env = t:match("\\\\begin%{(basiccode)%}")
                  or t:match("\\\\begin%{(screencode)%}")
                  or t:match("\\\\begin%{(screenoutputlined)%}")
                  or t:match("\\\\begin%{(tcolorbox)%}")
      if env then
        local code_buf = {}
        local after_begin = t:gsub("^[\n\r\t\f\v]*", "")
        -- Strip any content before \begin{...}
        after_begin = after_begin:gsub(".-\\\\begin%b{}", "")
        -- If same paragraph contains the end, finish here
        local inline_body = after_begin:match("(.-)\\\\end%{" .. env .. "%}")
        if inline_body then
          if env == 'tcolorbox' then
            local body = extract_code_from_tcolorbox(inline_body)
            if body then
              out:insert(make_screen_block(body))
            else
              out:insert(b)
            end
          else
            table.insert(code_buf, inline_body)
            out:insert(make_screen_block(table.concat(code_buf, "\n")))
          end
          i = i + 1
        else
          -- Collect following blocks until an end is found
          i = i + 1
          while i <= #blocks do
            local nb = blocks[i]
            local txt = pandoc.utils.stringify(nb)
            local end_pat = "\\\\end%{" .. env .. "%}"
            if txt:match(end_pat) then
              local pre = txt:gsub(end_pat .. ".*$", "")
              if #pre > 0 then table.insert(code_buf, pre) end
              out:insert(make_screen_block(table.concat(code_buf, "\n")))
              i = i + 1
              break
            end
            -- Stop if a new begin appears to avoid swallowing content
            if txt:match("\\\\begin%{(basiccode|screencode|screenoutputlined|tcolorbox)%}") then
              local collected = table.concat(code_buf, "\n")
              if env == 'tcolorbox' then
                local body = extract_code_from_tcolorbox(collected)
                if body then
                  out:insert(make_screen_block(body))
                else
                  out:insert(nb)
                end
              else
                out:insert(make_screen_block(collected))
              end
              -- do not consume this block; outer loop will handle
              break
            end
            table.insert(code_buf, txt)
            i = i + 1
          end
        end
      else
        out:insert(b)
        i = i + 1
      end
    else
      out:insert(b)
      i = i + 1
    end
  end
  return out
end

return {
  { RawBlock = RawBlock, Blocks = Blocks,
    Para = function(el)
      local t = pandoc.utils.stringify(el)
      local body = t:match("^%s*\\begin%{(basiccode|screencode|screenoutputlined)%}%s*(.-)%s*\\end%{%1%}%s*$")
      if body then
        return make_screen_block(body)
      end
      return nil
    end,
    Plain = function(el)
      local t = pandoc.utils.stringify(el)
      local body = t:match("^%s*\\begin%{(basiccode|screencode|screenoutputlined)%}%s*(.-)%s*\\end%{%1%}%s*$")
      if body then
        return make_screen_block(body)
      end
      return nil
    end,
  }
}


