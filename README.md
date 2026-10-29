# AirPods Handoff for NixOS

Событийный инструмент для передачи звука между **AirPods Pro 2 USB-C, iPhone и Linux**. Использует существующее Bluetooth-соединение, Apple AACP и отдельный автомат Audio Ownership. Не переключает наушники циклом `disconnect → connect`.

**Статус: experimental / hardware validation in progress.** Это не официальный Apple Automatic Switching, не интеграция с iCloud и не обещание полной совместимости с любыми AirPods/iOS.

[English summary](README.en.md) · [Архитектура](docs/architecture.md) · [Ручные проверки](docs/manual-tests.ru.md) · [Лицензии и источники](THIRD_PARTY_NOTICES.md)

## Что работает, а что ещё нет

| Возможность | Статус |
|---|---|
| iPhone на паузу → Play в Cider → звук на Linux | Проверено на одном комплекте AirPods Pro 2 USB-C |
| Play на iPhone → возврат звука с Linux на iPhone | Проверено на том же комплекте |
| Автопауза сопоставленного локального плеера при уступке телефону | Проверено с Cider; исправлена двухэтапная последовательность событий ownership/source |
| Локальная музыка дольше 30 секунд | Проверено: прежний конфликт таймеров устранён |
| Распознавание уже идущего звонка iPhone | Наблюдалось на устройстве; тип `call` блокирует захват |
| Звонок/неизвестный источник во время команды, поздний ACK, сон, потеря связи | Покрыто автоматическими тестами; полная аппаратная матрица не пройдена |
| Исключение Notification/Event, capture и виртуальных фильтров из инициаторов захвата | Покрыто тестами; все реальные приложения не проверены |
| Linux Play поверх **продолжающейся музыки** iPhone | Реализована guarded `take-media`; **на слух ещё не подтверждено** |
| Восстановление зависшего A2DP | Один suspend/resume существующего sink; в проверенных переходах помогал. Встречались задержки/ошибки транспорта, стабильность не гарантирована |
| YouTube/Spotify и другие MPRIS-плееры | Поддержка предусмотрена; аппаратно подтверждён прежде всего Cider |
| Полное различение фонового autoplay и пользовательского клика | Не реализовано: MPRIS/PipeWire не всегда дают такое различие |
| Любой звук приложения без MPRIS | Не реализовано; любой новый поток намеренно не считается командой захвата |
| Установка/сопряжение/сканирование AirPods самим инструментом | Не реализовано и не требуется для обычного handoff |
| AirPods других моделей, другие адаптеры/прошивки | Не проверены |
| Home Manager / другие дистрибутивы | Готовый модуль здесь только NixOS; ручной запуск возможен без гарантии поддержки |

Подтверждение `owns=1` само по себе **не доказывает**, что наушники уже воспроизводят Linux. В журнале отдельно различаются owner, AudioSource, тип источника и состояние A2DP/PipeWire. Слышимость проверяет человек.

## Требования

- NixOS с PipeWire, WirePlumber, `pipewire-pulse` и BlueZ.
- Desktop user session с D-Bus/MPRIS и `graphical-session.target`.
- AirPods уже сопряжены и доверены Linux; iPhone также сопряжён с ними.
- Оба хоста должны быть доступны наушникам; проверяйте `multipoint ready` и `hosts local-and-remote`.
- Для reverse-engineered multipoint обычно нужен Apple Bluetooth DeviceID. Модуль делает это **только при явном** `spoofAppleDeviceId = true`.

Разработка и локальная сборка проверены на **NixOS 26.05, x86_64-linux, Zig 0.16**. Flake фиксирует использованный nixpkgs. Выходы для aarch64-linux объявлены, но на ARM сборка и оборудование не проверялись. Для старых nixpkgs может отсутствовать `zig_0_16`.

## Установка на NixOS с flakes

Репозиторий пока подготовлен локально. После публикации замените `OWNER` на владельца GitHub-репозитория. До публикации можно добавить **локальную** папку как input.

В `flake.nix` добавьте:

```nix
inputs.airpods-handoff.url = "path:/home/alice/Documents/airpods-handoff-nixos";
# После публикации вместо path:
# inputs.airpods-handoff.url = "github:OWNER/airpods-handoff-nixos";
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

Таймеры политики пока настраиваются в исходниках: debounce 650 мс, окно нового намерения 6 с, idle release 4 с, cooldown 2,5 с, ограничение попыток восстановления sink. Это не бесконечный опрос: основной путь работает от D-Bus/PipeWire/AACP-событий.

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

`play_to_ack_ms` — задержка до ownership ACK, не акустическая задержка. На исходном комплекте были значения примерно 2–5 с от Play до ACK, значительная часть ожидания приходилась на запоздавший idle телефона; восстановление A2DP в успешных переходах занимало ещё около секунды. Эти единичные замеры не являются benchmark/p95 и не описывают новый захват поверх активной музыки.

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
