# AirPods Handoff for NixOS

Событийный инструмент для передачи звука между **AirPods Pro 2 USB-C, iPhone и Linux**. Использует существующее Bluetooth-соединение, Apple AACP и отдельный автомат Audio Ownership. Не переключает наушники циклом `disconnect → connect`.

**Статус: experimental / hardware validation in progress.** Это не официальный Apple Automatic Switching, не интеграция с iCloud и не обещание полной совместимости с любыми AirPods/iOS.

[English summary](README.en.md) · [Архитектура](docs/architecture.md) · [Ручные проверки](docs/manual-tests.ru.md) · [Лицензии и источники](THIRD_PARTY_NOTICES.md)

## Возможности и границы

Версия **0.3.0**, экспериментальная. Последний повторный конфликт на тестовом комплекте потребовал ручного возврата. Не устанавливайте с ожиданием бесшовности и надёжности macOS.

| Возможность | Что проверено |
|---|---|
| Новый Play на ПК поверх музыки iPhone | Cider подтверждён на слух на одном комплекте AirPods Pro 2 USB-C |
| Приоритет продолжающегося звука ПК | Локальные release/Pause запрещены до паузы/конца сеанса; самостоятельный захват прошивкой может потребовать возврата |
| Звонки Discord/Telegram | Duplex/Communication detection, mute/тишина не завершают сеанс; Discord проверен на оборудовании, Telegram — пока программными тестами |
| Звонок iPhone / неизвестный источник | Контроллер заново запрашивает состояние и запрещает захват call/unknown |
| Повторный конфликт | Один автоматический возврат подтверждённого локального сеанса, затем `LOCAL_CONTESTED` и явная кнопка/CLI возврата |
| Ручное закрепление за ПК | Сохраняется между запусками; приоритет локальной политики, не закрытый Apple firmware lock |
| Потоки без MPRIS | Fallback для известных медиаприложений и явных media roles; неизвестные приложения, autoplay и непрерывная тишина не классифицируются идеально |
| Зависшие A2DP/PipeWire links | Ремонт paused/init выходных связей и ограниченный suspend/resume существующего sink; Bluetooth не переподключается |
| Быстрый возврат | Явная ошибка запускает ремонт сразу, поздние связи обрабатываются по событию. Убраны лишние 800 мс и 300 мс в соответствующих ветках; мгновенный звук не гарантируется |
| Сон / потеря связи / поздние ACK | Старые намерения и токены отменяются; свежий baseline после сна. Полная физическая матрица ещё не пройдена |
| Панель Noctalia | Опциональная интеграция для Noctalia 5.2 / Luau API 24: статус, Авто, закрепление и возврат |

Нет интеграции Apple Account/iCloud, доказанного межустройственного protected-call signaling, пространственного аудио или гарантии работы со всеми AirPods/iOS/адаптерами. Начальное подключение и сопряжение остаются за BlueZ/пользователем. Инструмент не добавляет циклический поиск при входе в систему.

## Требования

- NixOS с PipeWire, WirePlumber, `pipewire-pulse` и BlueZ.
- Desktop user session с D-Bus/MPRIS и `graphical-session.target`.
- AirPods уже сопряжены и доверены Linux; iPhone также сопряжён с ними.
- Оба хоста должны быть доступны наушникам; проверяйте `multipoint ready` и `hosts local-and-remote`.
- Для reverse-engineered multipoint обычно нужен Apple Bluetooth DeviceID. Модуль делает это **только при явном** `spoofAppleDeviceId = true`.

Разработка и локальная сборка проверены на **NixOS 26.05, x86_64-linux, Zig 0.16**. Flake фиксирует использованный nixpkgs. Выходы для aarch64-linux объявлены, но на ARM сборка и оборудование не проверялись. Для старых nixpkgs может отсутствовать `zig_0_16`.

## Установка на NixOS с flakes

Добавьте репозиторий как flake input. Для локальной разработки можно использовать `path:`.

В `flake.nix` добавьте:

```nix
inputs.airpods-handoff.url = "github:Redm00use/Airpods-Handoff-NixOS";
```

В существующий список `modules` вашего `nixosSystem` добавьте модуль и настройки. **Не заменяйте** весь конфиг машины этим примером:

```nix
outputs = { self, nixpkgs, ... }@inputs: {
  nixosConfigurations.HOST = nixpkgs.lib.nixosSystem {
    system = "x86_64-linux";
    modules = [
      ./configuration.nix
      inputs.airpods-handoff.nixosModules.default
      {
        services.airpodsHandoff = {
          enable = true;
          user = "alice";                    # ваш существующий пользователь
          device = "AA:BB:CC:DD:EE:FF";        # MAC именно ваших AirPods
          spoofAppleDeviceId = true;
          shadow = false;
        };
      }
    ];
  };
};
```

Узнать адрес можно командой `bluetoothctl devices`. Не копируйте адрес-заглушку из примера.

```bash
sudo nixos-rebuild switch --flake /etc/nixos#HOST
```

Если ваш flake расположен иначе, укажите его путь. Модуль не создаёт пользователя, не устанавливает пароль и не трогает ключи сопряжения.

## Установка через обычные imports

Разместите **весь репозиторий**, включая `src/` и `vendor/`, например в `/etc/nixos/airpods-handoff-nixos`. В `configuration.nix`:

```nix
{
  imports = [ ./airpods-handoff-nixos/nix/module.nix ];

  services.airpodsHandoff = {
    enable = true;
    user = "alice";
    device = "AA:BB:CC:DD:EE:FF";
    spoofAppleDeviceId = true;
  };
}
```

Применение: `sudo nixos-rebuild switch`. Нужен nixpkgs с Zig 0.16 и остальными зависимостями пакета.

## Первое подключение и запуск

1. Сопрягите AirPods стандартными средствами BlueZ. Не удаляйте работающие сопряжения без причины.
2. При необходимости разрешите доверие: `bluetoothctl trust ВАШ_MAC`.
3. Подключите Linux и iPhone обычным способом. Инструмент не устанавливает начальное Bluetooth-соединение и не включает автопоиск при входе.
4. После смены DeviceID некоторым устройствам может понадобиться повторное сопряжение. Настройка DeviceID действует на весь адаптер; её применение может перезапустить Bluetooth и временно отключить другие Bluetooth-устройства.
5. Запускайте службы от своего desktop-пользователя, **без sudo**:

```bash
systemctl --user start airpodsctl.service airpods-auto-switch.service
systemctl --user status airpodsctl.service airpods-auto-switch.service
```

Обычно они стартуют вместе с `graphical-session.target`. Если compositor не управляет этим target, запуск нужно интегрировать в его systemd-сессию. Простой `nix profile install` сам по себе службы не настраивает.

```bash
airpodsctl --session switching status
```

Ожидаемый пример:

```text
multipoint ready
hosts local-and-remote
owner remote
remote-activity idle
```

Не запускайте одновременно другие AACP-демоны: LibrePods, EarPort, airpods-tui или прежний собственный `airpodsctl serve`. Они могут конкурировать за канал. Если ранее были ручные unit-файлы в `~/.config/systemd/user/`, они перекрывают декларативные: проверьте `systemctl --user cat airpodsctl airpods-auto-switch` и сохраните/уберите старые overrides перед миграцией.

## Безопасная пробная проверка

Можно сначала включить:

```nix
services.airpodsHandoff.shadow = true;
```

После rebuild обработчик пишет решения, но не отправляет ownership/Pause/sink-команды. Контроллер при этом открывает AACP-канал и запрашивает статус: это не полностью пассивный Bluetooth-сниффер.

Для ручного запуска пакета без установки служб:

```bash
nix run .#airpodsctl -- --device ВАШ_MAC serve --auto-switch=external
# В другом терминале:
nix run . -- --device ВАШ_MAC --shadow
```

Не запускайте эти экземпляры поверх уже работающих служб.

## Настройки модуля

| Опция `services.airpodsHandoff` | Назначение |
|---|---|
| `enable` | Включить модуль |
| `user` | Пользователь desktop-сессии; обязательно |
| `device` | Адрес уже сопряжённых AirPods; обязательно |
| `spoofAppleDeviceId` | Apple DeviceID адаптера; по умолчанию `false` |
| `shadow` | Только решения/логи; по умолчанию `false` |
| `package` | Переопределить согласованный пакет обработчика и контроллера |

Таймеры политики пока настраиваются в исходниках: debounce нового Play 650 мс, окно намерения 6 с, idle release 4 с, cooldown 2,5 с. Для восстановления уже подтверждённого локального сеанса отдельные 300 мс ожидания удалены. Попытки восстановления sink ограничены. Это не бесконечный опрос: основной путь работает от D-Bus/PipeWire/AACP-событий.

## Ручное управление и панель

```bash
airpods-handoffctl status       # JSON, фактическое состояние
airpods-handoffctl watch        # события до завершения команды
airpods-handoffctl pin          # закрепить приоритет и один раз запросить возврат
airpods-handoffctl auto         # снять закрепление
airpods-handoffctl return       # одна новая ручная попытка после конфликта
```

Настройка сохраняется в `~/.config/airpods-handoff/preferences.json`. Статус/команды доступны через UNIX-сокет текущего пользователя (0600 + проверка UID), сетевого сервиса нет. Сохранённое закрепление само по себе не начинает захват при запуске демона и не подключает Bluetooth.

[Установка панели Noctalia](integrations/noctalia/README.md). Она опциональна и не требует личных скриптов, имён пользователей или MAC-адресов автора.

## Логи и диагностика

```bash
journalctl --user -u airpods-auto-switch -u airpodsctl -f
airpods-handoff-diagnose > handoff-diagnostic.txt
```

Диагностика не читает Bluetooth-ключи, plist, пароли или профили браузера. Она содержит состояние служб, имена аудиоприложений и локальные пути; просмотрите файл перед публикацией.

- `LOCAL_CLAIMED`: ownership подтверждено, фактический Linux AudioSource ещё не подтверждён.
- `LOCAL_OWNED`: AirPods сообщили Linux как источник; для готовности аудио дополнительно нужен active transport и Running sink.
- `REMOTE_CALL`: удалённый источник обозначен как звонок, захват заблокирован.
- `DEGRADED`: данных недостаточно; неизвестность не разрешает захват.
- `audio recovery ... no further retries`: попытка ограничена; это не сообщение «звук точно работает».

`play_to_ack_ms` — время до ownership ACK, не до слышимого звука. В одном ускоренном переходе ACK→готовность графа составила 264 мс; пользователь сначала не заметил явного улучшения. Финальная дополнительная оптимизация ещё требует слуховой проверки. Подробнее: [результаты и ограничения](docs/verification.md).

## Тесты и сборка

```bash
nix flake check --print-build-logs
nix build
nix run . -- --help
```

Для разработки:

```bash
nix develop
python3 -m unittest discover -s tests -p 'test_*.py' -v
(cd vendor/airpodsctl && zig build core-check --summary all)
```

Проверяются FSM/гонки, поздние ACK, уведомления, одновременное воспроизведение, call guard, resume, peer yield, bounded audio recovery и IPC. Core-тесты контроллера используют эмулятор; полный upstream D-Bus integration suite в сборку не включён. [Ручная матрица](docs/manual-tests.ru.md) нужна отдельно: тесты не слышат AirPods.

## Удаление

Установите `services.airpodsHandoff.enable = false`, выполните rebuild и остановите службы, если они остались активны:

```bash
systemctl --user stop airpods-auto-switch airpodsctl
```

Если ранее включали `spoofAppleDeviceId`, после отключения модуля перепроверьте DeviceID в собственном конфиге. Отключение модуля может поменять идентификацию адаптера, но не удаляет Bluetooth-сопряжения и пользовательские файлы.

## Лицензия и благодарности

MIT. Вендорная локально изменённая версия `hacel/airpodsctl` сохраняет собственное MIT-уведомление. Точная исходная ревизия записана в `vendor/airpodsctl/UPSTREAM`. Ориентиры airpods-tui, earport-handoff и LibrePods перечислены в `THIRD_PARTY_NOTICES.md`; их демоны не входят в установку.

Не связано с Apple. Все товарные знаки принадлежат их владельцам.

Аппаратные результаты и оставшиеся ограничения: [журнал проверки](docs/verification.md). Короткие провалы при переключении ещё возможны.
