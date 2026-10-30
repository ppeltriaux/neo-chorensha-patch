-- Sound recorder (Plan 4 Task 2, driven by tools/record_sound.py; MAME's -wavwrite holds the audio).
-- Title -> CONFIG (Down Down A) -> BGM PLAY (Down x3, REC_MODE=tunes) or PCM PLAY (Down x2,
-- REC_MODE=effects), then the plan. It logs, one event per line, "<emulated s> <kind> ...":
--   base <hex> frame <n>           the program was found
--   t0 frame <n>                   the menu item is reached (90 frames after the last Down)
--   action <a> frame <n>           a plan action was taken
--   call <off> d0=<hex> d1=<hex>   an instruction at game offset <off> ran (read tap on its opcode):
--                                  MCDRV trap #4 fn $01 $15D6, fn $05 $15DA/$15EC, fn $02 (play) $15DE,
--                                  fn $14 $15FE; IOCS _ADPCMOUT $3B3C, _ADPCMSNS $3AE8,
--                                  _ADPCMMOD $3B14 and CONFIG's stop $2FE8
--   opm <reg> <val>                an OPM write to register $08 (key on/off) or $10/$11 (Timer A)
--   msm <addr> <val>               a write to the MSM6258 ($E92001/$E92003; REC_MODE=tunes only)
-- REC_MODE=boot ends the run once the program is found (tools/record_sound.py's SRAM run).
-- Env: REC_LOG (the log file), REC_MODE, REC_PLAN = "sec:action,..." with times in seconds after
-- t0; actions tNN (BGM PLAY number NN hex, then A: stop + play), pNN (PCM PLAY cue NN hex, then
-- A: stop, 2 frames, se_play), Q (close the log, RESULT PASS).
local lib = dofile(os.getenv("X68K_DIR") .. "/lib.lua")
local G = lib.G
local cpu = manager.machine.devices[":maincpu"]
local mem = cpu.spaces["program"]
local mode = os.getenv("REC_MODE")
if mode ~= "tunes" and mode ~= "effects" and mode ~= "boot" then
  error("REC_MODE must be tunes, effects or boot")
end
local log = assert(io.open(assert(os.getenv("REC_LOG"), "REC_LOG missing"), "w"))
local function now() return manager.machine.time:as_double() end
local function emit(fmt, ...) log:write(string.format("%.9f " .. fmt .. "\n", now(), ...)) end

local plan = {}
for item in (os.getenv("REC_PLAN") or ""):gmatch("[^,]+") do
  local t, a = item:match("^([%d%.]+):(%w+)$")
  assert(t, "bad REC_PLAN item " .. item)
  plan[#plan + 1] = { t = tonumber(t), a = a }
end

local CALL_SITES = { 0x15D6, 0x15DA, 0x15DE, 0x15EC, 0x15FE, 0x3B3C, 0x3AE8, 0x3B14, 0x2FE8 }
local OPM_LOGGED = { [0x08] = true, [0x10] = true, [0x11] = true }
local taps = {}  -- kept so the taps are not garbage-collected
local title_at, t0

local function arm()
  local b = lib.base()
  for _, off in ipairs(CALL_SITES) do
    taps[#taps + 1] = mem:install_read_tap(b + off, b + off + 1, "rec" .. off, function()
      local pc = cpu.state["PC"].value - b
      if pc >= off and pc <= off + 2 then
        emit("call %04X d0=%08X d1=%08X", off, cpu.state["D0"].value, cpu.state["D1"].value)
      end
    end)
  end
  lib.read_tap(G.str_title, "rec_title", function(_, pc)
    if not title_at and pc >= 0x33E8 and pc <= 0x341E then title_at = lib.frame() end
  end)
  -- OPM (YM2151): register number at $E90001, data at $E90003 (byte writes)
  local reg = 0
  taps[#taps + 1] = mem:install_write_tap(0xE90000, 0xE90003, "rec_opm", function(o, d)
    if o <= 0xE90001 then reg = d & 0xFF
    elseif OPM_LOGGED[reg] then emit("opm %02X %02X", reg, d & 0xFF) end
  end)
  if mode == "tunes" then
    taps[#taps + 1] = mem:install_write_tap(0xE92000, 0xE92003, "rec_msm", function(o, d)
      emit("msm %06X %04X", o, d & 0xFFFF)
    end)
  end
end

-- title: Down Down A (CONFIG); CONFIG: Down to PCM PLAY (item 2) or BGM PLAY (item 3)
local menu = { { 0, "P1 Down" }, { 30, "P1 Down" }, { 60, "P1 A" }, { 150, "P1 Down" }, { 180, "P1 Down" } }
if mode == "tunes" then menu[#menu + 1] = { 210, "P1 Down" } end
local T0_AT = 300

local next_i = 1
lib.on_frame(function(f)
  if not lib.base() then
    if not lib.try_program(0x050F40) and f % 60 == 0 then lib.find_program() end
    if lib.base() then
      arm() emit("base %06X frame %d", lib.base(), f)
      if mode == "boot" then log:close() lib.pass() end
    end
    return
  end
  if not title_at then return end
  local u = f - title_at - 90
  for _, s in ipairs(menu) do if s[1] == u then lib.press(s[2], 6) end end
  if u == T0_AT then t0 = now() emit("t0 frame %d", f) end
  if not t0 then return end
  local p = plan[next_i]
  if not p or now() - t0 < p.t then return end
  next_i = next_i + 1
  emit("action %s frame %d", p.a, f)
  local kind, num = p.a:sub(1, 1), tonumber(p.a:sub(2), 16)
  if kind == "t" then lib.w16(0x17514, num) lib.press("P1 A", 6)
  elseif kind == "p" then lib.w16(0x17512, num) lib.press("P1 A", 6)
  elseif p.a == "Q" then log:close() lib.pass()
  else lib.fail("unknown action " .. p.a) end
end)
