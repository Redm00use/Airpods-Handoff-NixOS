local state = {available=false,title="AirPods Handoff",detail="Подключаюсь к обработчику…"}
local streaming = false
local busy = false
local actionError = nil

local function decode(raw)
  local ok,value=pcall(noctalia.json.decode,raw or "{}")
  if ok and type(value)=="table" then return value end
  return {}
end

local function render()
  panel.render(ui.scroll({gap=12,padding=12},{
    ui.row({gap=10,align="center"},{ui.glyph({name="device-airpods",size=25}),ui.label({text="AirPods Handoff",fontSize=20,fontWeight="bold"})}),
    ui.label({text=state.title or "Состояние недоступно",fontSize=16,fontWeight="bold",maxLines=2}),
    ui.label({text=actionError or state.detail or "",fontSize=13,color="secondaryText",maxLines=3}),
    ui.row({gap=8},{
      ui.button({text="Авто",selected=state.available and not state.pinned,enabled=state.available and not busy,onClick=function() control("auto") end}),
      ui.button({text=state.pinned and "Закреплено за ПК" or "Закрепить за ПК",glyph="pin",selected=state.pinned==true,enabled=state.available and not busy,tooltip="Не отдавать приоритет автоматически, даже на паузе. Самостоятельное переключение AirPods остаётся возможным.",onClick=function() control(state.pinned and "auto" or "pin") end})
    }),
    ui.button({text=state.conflict and "Повторить возврат на ПК" or "Вернуть звук на ПК",glyph="arrow-back-up",enabled=state.can_return==true and not busy and not state.pending,onClick=function() control("return") end})
  }))
end

local function subscribe()
  if streaming then return end
  streaming=true
  local started=noctalia.runStream("airpods-handoffctl watch",function(line)
    state=decode(line)
    if state.available==false then streaming=false end
    render()
  end)
  if not started then streaming=false end
end
function control(action)
  if busy then return end
  busy=true;actionError=nil;render()
  noctalia.runAsync({"airpods-handoffctl",action},function(result)
    busy=false
    local reply=decode(result.stdout)
    if result.exitCode~=0 or reply.ok~=true then actionError=reply.error or "Команда не выполнена."
    else state=reply end
    render()
  end)
end
function onOpen() render();subscribe() end
function update() noctalia.setUpdateInterval(5000);subscribe() end
