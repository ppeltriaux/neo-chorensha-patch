-- Helpers for scripts running the original game in MAME x68000.
-- Env: SZ2_SIG (hex of the first 64 text bytes, '??' = masked), X68K_FRAMES, X68K_SNAP_DIR.
-- Loaded once per MAME run: a second dofile returns the same table (one frame counter,
-- one frame_done hook), so a script and a module it loads (autoplay.lua) can share it.
if X68K_LIB then return X68K_LIB end
local lib = {}

-- Game-relative offsets (base-0 image offsets; add lib.base()) of the original's globals.
-- How each was found: docs/notes/game-globals.md. All words unless noted.
lib.G = {
  debug        = 0x221F0, -- debug flag (KAKUSI gate); main clears it, nothing sets it
  muteki       = 0x221F8, -- KAKUSI invincibility: non-zero skips the player hit test
  stage        = 0x221FA, -- 1, 2, 3 = the bonus stage; 4 wraps to 1
  acchoh       = 0x221F6, -- KAKUSI "ACCHOH": extra random enemies in stage 1
  score        = 0x22200, -- long, binary; shown in hex on the HUD
  score_add    = 0x221FC, -- long, points pending, folded into score every 4th frame
  lives        = 0x221AC, -- spare ships (2 at start); dying at 0 ends the game
  bombs        = 0x22196, -- bombs in stock (3 at start and after a death; pickups add up to 8)
  game_over    = 0x2220A, -- 0 while playing; set to 1 ends the play loop (GAME OVER)
  game_state   = 0x2220A, -- no state variable exists: see game-globals.md "Game state"
  frame        = 0x22210, -- game frame counter (counts only inside the play loop)
  phase        = 0x2B8A6, -- stage script phase: $100 start ... $1x0 sections, $200 clear
  phase_timer  = 0x2B8A8, -- frames since the phase began
  boss         = 0x22208, -- boss alive: boss handlers set $20 each frame, decays to 0
  death_timer  = 0x221A8, -- 0 alive; counts up from the hit (respawn at $51)
  invuln       = 0x221AA, -- post-respawn invulnerability frames ($100 at spawn)
  player_x     = 0x27894, -- 1/64 px, clamped $400-$4000
  player_y     = 0x27892, -- 1/64 px, clamped $400-$3F00
  char_table   = { base = 0x278A6, size = 0x80, count = 128, handler = 0x18,
                   alloc_bitmap = 0x27896 }, -- object array; +$18 = per-frame handler (long)
  str_title    = 0x29D0,  -- "START" (read when the title menu is drawn)
  str_gameover = 0x3FA8,  -- the game over's text
  str_kakusi   = 0x30CA,  -- KAKUSI's header
}

local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local mem = cpu.spaces["program"]
local frame = 0
local handlers = {}
local timers = {}      -- {at=frame, fn=fn}
local base = nil

lib.frame = function() return frame end

local function sig_bytes()
  local hex = os.getenv("SZ2_SIG")
  assert(hex and #hex == 128, "SZ2_SIG missing")
  local t = {}
  for i = 1, 64 do
    local h = hex:sub(2 * i - 1, 2 * i)
    t[i] = (h ~= "??") and tonumber(h, 16) or false
  end
  return t
end

-- Scan RAM for the game text; returns base address or nil (cached once found).
function lib.find_program(force)
  if base and not force then return base end
  if force then base = nil end
  local sig = sig_bytes()
  local first
  for i = 1, 64 do if sig[i] then first = i break end end
  for a = 0x6800, 0xBFFFC0, 2 do
    local ok = true
    -- cheap reject on the first unmasked byte
    if mem:read_u8(a + first - 1) ~= sig[first] then ok = false end
    if ok then
      for i = 1, 64 do
        if sig[i] and mem:read_u8(a + i - 1) ~= sig[i] then ok = false break end
      end
    end
    if ok then base = a return a end
  end
  return nil
end

-- Check for the game text at one address (cheap); sets the base when it matches.
function lib.try_program(addr)
  local sig = sig_bytes()
  for i = 1, 64 do
    if sig[i] and mem:read_u8(addr + i - 1) ~= sig[i] then return nil end
  end
  base = addr
  return addr
end

function lib.base() return base end
function lib.u8(off)  assert(base, "program not located") return mem:read_u8(base + off) end
function lib.u16(off) assert(base, "program not located") return mem:read_u16(base + off) end
function lib.u32(off) assert(base, "program not located") return mem:read_u32(base + off) end
function lib.w16(off, v) assert(base, "program not located") mem:write_u16(base + off, v) end

-- Memory taps on game-relative words. fn(value, pc) gets the written/read word and the
-- game-relative pc (pc is the cpu PC when the access happens, i.e. just past the opcode);
-- a write tap may return a value to replace the one written. Handles are kept here so
-- they are not garbage-collected (which would remove the tap).
local taps = {}
local function tap(kind, off, name, fn)
  assert(base, "program not located")
  local a = base + off
  local install = (kind == "w") and mem.install_write_tap or mem.install_read_tap
  taps[#taps + 1] = install(mem, a, a + 1, name, function(o, d, m)
    local pc = cpu.state["PC"].value - base
    return fn(d, pc, m)
  end)
end
function lib.write_tap(off, name, fn) tap("w", off, name, fn) end
function lib.read_tap(off, name, fn) tap("r", off, name, fn) end

local function joy(name)
  for tag, port in pairs(machine.ioport.ports) do
    if tag:find("joy1") then
      local f = port.fields[name]
      if f then return f end
    end
  end
  error("no joystick field " .. name)
end
function lib.field(name) return joy(name) end

function lib.hold(field)    if type(field) == "string" then field = joy(field) end field:set_value(1) end
function lib.release(field) if type(field) == "string" then field = joy(field) end field:set_value(0) end
function lib.press(field, frames)
  if type(field) == "string" then field = joy(field) end
  field:set_value(1)
  timers[#timers + 1] = { at = frame + (frames or 4), fn = function() field:set_value(0) end }
end

function lib.on_frame(fn) handlers[#handlers + 1] = fn end

-- Fraction of non-black pixels in the field, excluding the left drive-LED strip.
function lib.nonblack_fraction()
  local scr = machine.screens[":screen"]
  local w, h = scr.width, scr.height
  local px = scr:pixels()
  local x0 = 16
  local n, tot = 0, 0
  for y = 0, h - 1, 2 do
    local row = y * w * 4
    for x = x0, w - 1, 2 do
      local o = row + x * 4 + 1
      local b, g, r = px:byte(o, o + 2)
      tot = tot + 1
      if (b | g | r) ~= 0 then n = n + 1 end
    end
  end
  return n / tot
end

function lib.snapshot() machine.video:snapshot() end

function lib.pass()
  print("RESULT PASS")
  machine:exit()
end
function lib.fail(msg)
  print("RESULT FAIL " .. tostring(msg))
  machine:exit()
end

emu.register_frame_done(function()
  frame = frame + 1
  for i = #timers, 1, -1 do
    if frame >= timers[i].at then local t = table.remove(timers, i) t.fn() end
  end
  for _, h in ipairs(handlers) do h(frame) end
  local maxf = tonumber(os.getenv("X68K_FRAMES") or "0")
  if maxf > 0 and frame > maxf + 600 then lib.fail("frame budget exceeded") end
end)

X68K_LIB = lib
return lib
