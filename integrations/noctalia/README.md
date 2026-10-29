# Панель Noctalia

Для **Noctalia 5.2 / Luau plugin API 24**. Это не плагин для классической QML-версии Noctalia. Ядро handoff работает и без панели.

1. Установите NixOS-модуль из основного README: вместе с ним появится `airpods-handoffctl`.
2. Скопируйте поставляемый плагин в свой каталог path-плагинов:

   ```bash
   nix build github:Redm00use/Airpods-Handoff-NixOS --out-link /tmp/airpods-handoff-package
   mkdir -p ~/.local/share/noctalia-user-plugins
   cp -r /tmp/airpods-handoff-package/share/airpods-handoff/noctalia \
     ~/.local/share/noctalia-user-plugins/airpods-handoff
   ```

3. В существующем `~/.config/noctalia/config.toml` добавьте `local/airpods_handoff` в массив `[plugins].enabled`, сохранив другие плагины. Если path-источник ещё не настроен, добавьте его (замените `alice`):

   ```toml
   [[plugins.source]]
   name = "personal-tools"
   kind = "path"
   location = "/home/alice/.local/share/noctalia-user-plugins"
   enabled = true
   ```

4. Примените настройки средствами Noctalia. Открыть панель:

   ```bash
   noctalia msg config-reload
   noctalia msg panel-open local/airpods_handoff:status
   ```

По желанию привяжите открытие к уже существующему значку Bluetooth:

```toml
[widget.bluetooth]
type = "custom_button"
glyph = "bluetooth"
label = ""
tooltip = "Bluetooth / AirPods"

[widget.bluetooth.actions]
left = "panel-toggle local/airpods_handoff:status"
right = "panel-toggle control-center bluetooth"
```

Объедините эти поля с существующими секциями, не создавайте дубликаты TOML-таблиц. Для подключения сохранённого path-плагина может понадобиться обычная перезагрузка конфигурации; `.luau`-изменения поддерживают горячую загрузку.

Панель показывает фактический источник, состояние звонка/восстановления/конфликта и предоставляет:

- **Авто** — обычная политика переключения.
- **Закрепить за ПК** — сохраняемый локальный приоритет, в том числе на паузе.
- **Вернуть звук на ПК / Повторить возврат** — одна новая явная попытка, без Bluetooth reconnect.

Статус передаётся событийным локальным потоком `airpods-handoffctl watch`. Нет дополнительного опроса Bluetooth. Панель не управляет батареями/ANC: для этого можно оставить существующие инструменты.

Закрепление не является доказанным firmware-level lock Apple: AirPods могут самостоятельно переключить канал. Повторный конфликт намеренно прекращает автоматическую борьбу и предлагает ручной возврат. Во время известного звонка iPhone возврат блокируется. Тексты статуса пока на русском.
