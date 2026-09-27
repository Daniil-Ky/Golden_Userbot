`This file is part of Golden Userbot.
Licensed under the GNU General Public License v3.0.

You may redistribute and/or modify this file under the terms of the
GNU General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

This file is distributed WITHOUT ANY WARRANTY; without even the implied
warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the LICENSE file for the full license text.`

# Golden Userbot 26.3.0

Golden Userbot — Telegram Userbot для автоматизации работы с MineEVO,
повторной отправки сообщений, расчёта курсов, переводов лимитов,
автоматической обработки промокодов и работы с inline-сообщениями и кнопками.

## Что входит в проект

Проект состоит из двух связанных частей:

- **Golden Userbot** — основная логика, команды и автоматические функции.
- **Golden Userbot Helper** — отдельный Telegram-бот, который нужен для
  публикации inline-результатов и работы с callback/URL-кнопками.

В актуальной архитектуре Userbot и Helper могут запускаться в одном Render
Web Service через `launcher.py`. Они работают в одном Python-процессе и одном
`asyncio`-цикле. Это означает, что для связи между ними больше не требуется
отдельный публичный HTTP-переход `USERBOT_URL`/`HELPER_URL`.

## Возможности

### MineEVO

- `.work` — сохраняет текущий чат как рабочий чат MineEVO.
- `.evo` — отправляет команду в MineEVO и публикует его ответ через Helper.
- Поддерживаются URL-кнопки MineEVO.
- Поддерживаются callback-кнопки MineEVO.
- После нажатия callback-кнопки Userbot получает событие от Helper,
  нажимает соответствующую кнопку исходного сообщения MineEVO и обновляет
  уже опубликованное inline-сообщение.

### Повтор сообщений

- `.repeat` — повторная отправка текста или сообщения указанное количество
  раз с заданным интервалом.
- `.stoprepeat` — остановка активного повтора в текущем чате.
- Поддерживаются сообщения с форматированием и медиа.
- Статусные сообщения автоматически удаляются через заданное время.

### URL-кнопки

- `.urlbtn` создаёт сообщение через Helper с URL-кнопками.
- Можно указать несколько кнопок отдельными строками.
- Формат:

```text
.urlbtn Текст сообщения
Текст кнопки - https://example.com
Ещё кнопка - https://t.me/
```

### Курсы ресурсов

- `.tcset` — сохраняет сообщение с примером курса.
- `.tc` — рассчитывает курс для выбранной валюты или пары валют.
- Поддерживаются обозначения ресурсов, используемые текущим форматом MineEVO.
- Для одного ресурса формируется таблица курса с форматированием.
- Для двух ресурсов выводится взаимный курс.

### Калькулятор

`.calc` позволяет вычислять математические выражения.

Поддерживаются основные арифметические операции, скобки, проценты,
умножение/деление в альтернативной записи и квадратный корень.

Примеры:

```text
.calc 2+2*5
.calc 100+15%
.calc √81
```

### Переводы лимитов

- `.lmgroup` — сохраняет текущий чат как рабочий чат для переводов лимитов.
- `.lm НИК КОЛИЧЕСТВО` — запускает последовательный перевод.
- `.lmpause` — ставит перевод на паузу.
- `.lmresume` — продолжает перевод.
- `.lmstop` — полностью останавливает перевод.
- `.lchk` — показывает состояние перевода или время до следующего запуска.

Перед серией переводов Userbot определяет максимально доступную сумму,
используя пробный запрос MineEVO.

### Thx

- `.thxsource` — делает текущий чат источником событий и включает наблюдение.
- `.thxoff` — выключает наблюдение.
- При обнаружении события `активировал(а) бустер!` Userbot отправляет `Thx`
  указанному Thx-боту.

### Автоматические промокоды

Userbot периодически проверяет список действующих промокодов MineEVO.

Базовые коды, которые уже считаются известными:

```text
EVO
437
EVO2
DEV2
```

Новые коды проверяются отдельно командой `промо КОД`.

Код добавляется в `promo_seen` **только если ответ MineEVO точно совпадает с**:

```text
🎉 Промокод КОД активирован!
```

Если MineEVO не подтвердил активацию, код в `promo_seen` не записывается.

Проверка выполняется автоматически раз в час.

## Управление `promo_seen`

Список хранится в файле:

```text
userbot_config.txt
```

Поле конфигурации:

```text
promo_seen=EVO,437,EVO2,DEV2
```

Команды:

```text
.promoseen
```

Показывает текущий список. Каждый код выводится отдельной строкой и помещён
в `<code>...</code>`, поэтому его удобно копировать.

Добавление:

```text
.promoseen +КОД
```

Ответ:

```text
✅ Код КОД добавлен в promo_seen.
```

Удаление:

```text
.promoseen -КОД
```

Ответ:

```text
✅ Код КОД удалён из promo_seen.
```

Если код уже есть:

```text
⚠️ Код КОД уже находится в promo_seen.
```

Если удаляемого кода нет:

```text
⚠️ Код КОД отсутствует в promo_seen.
```

Новые переменные окружения для `promo_seen` не нужны.

## Что происходит после перезапуска Render

`promo_seen` хранится в `userbot_config.txt`, а не в переменной окружения.

Если файл конфигурации сохранился, Userbot загрузит сохранённый список.
Если файла нет, используются базовые значения:

```text
EVO,437,EVO2,DEV2
```

Само наличие значения в коде не означает, что сохранённый список каждый раз
принудительно сбрасывается. При наличии `userbot_config.txt` используется его
содержимое.

Важно: обычная файловая система Render не является гарантированным постоянным
хранилищем при каждом redeploy. Для гарантированного сохранения конфигурации
нужно использовать подходящее persistent storage либо другой внешний способ
хранения данных.

## Команды

| Команда | Назначение |
|---|---|
| `.work` | Подключить текущий чат MineEVO |
| `.evo` | Выполнить команду MineEVO |
| `.promoseen` | Показать `promo_seen` |
| `.promoseen +КОД` | Добавить код |
| `.promoseen -КОД` | Удалить код |
| `.urlbtn` | Создать сообщение с URL-кнопками |
| `.repeat` | Повторять сообщение |
| `.stoprepeat` | Остановить повтор |
| `.tcset` | Сохранить шаблон курса |
| `.tc` | Рассчитать курс |
| `.calc` | Вычислить выражение |
| `.lmgroup` | Выбрать чат для переводов лимитов |
| `.lm` | Запустить перевод лимитов |
| `.lmpause` | Поставить перевод на паузу |
| `.lmresume` | Продолжить перевод |
| `.lmstop` | Полностью остановить перевод |
| `.lchk` | Проверить состояние перевода |
| `.thxsource` | Включить наблюдение Thx |
| `.thxoff` | Выключить наблюдение Thx |

## Структура проекта

Рекомендуемая структура актуального проекта:

```text
Golden Userbot/
├── launcher.py
├── userbot.py
├── bot.py
├── requirements.txt
├── runtime.txt
├── README.md
└── userbot_config.txt
```

### `launcher.py`

Общая точка запуска проекта.

Он запускает Userbot и Helper в одном процессе, создаёт HTTP-сервер Render,
настраивает Telegram Webhook Helper и передаёт callback-события непосредственно
в Userbot.

### `userbot.py`

Основная логика Userbot: команды, MineEVO, промокоды, курсы, калькулятор,
переводы лимитов, Thx, повтор сообщений и интеграция с Helper.

### `bot.py`

Логика Helper Bot: Inline Mode, публикация результатов, URL-кнопки,
callback-кнопки и Telegram webhook.

### `requirements.txt`

Список Python-зависимостей проекта.

### `runtime.txt`

Фиксирует версию Python, с которой должен запускаться проект на Render.

### `userbot_config.txt`

Локальный файл настроек, создаваемый Userbot автоматически.

Не добавляйте его в GitHub, если в нём находятся данные, которые не должны
публиковаться.

## Переменные окружения Userbot

Основные переменные:

```text
API_ID
API_HASH
STRING_SESSION
HELPER_SECRET
```

Дополнительные:

```text
PORT
THX_BOT
LM_PROBE_SUM
```

### `API_ID`

Числовой API ID Telegram-приложения.

### `API_HASH`

API Hash Telegram-приложения.

### `STRING_SESSION`

Строковая Telethon-сессия аккаунта Userbot.

### `HELPER_SECRET`

Секрет для защищённых служебных HTTP-запросов Helper/Userbot.

### `PORT`

Порт веб-сервиса. Если переменная не задана, используется `10000`.

### `THX_BOT`

Имя Telegram-бота, которому отправляется `Thx`. По умолчанию используется
`@mineevo`.

### `LM_PROBE_SUM`

Сумма, используемая для пробного запроса при определении максимального
перевода лимитов. Значение по умолчанию — `3N`.

## Переменные окружения Helper / Render

Helper использует токен Telegram-бота, а Render должен иметь публичный URL
для Telegram Webhook.

В зависимости от текущего `bot.py`/`launcher.py` используются:

```text
BUTTON_BOT_TOKEN
WEBHOOK_SECRET
WEBHOOK_URL
```

`WEBHOOK_URL` может быть заменён автоматически доступным Render URL через
`RENDER_EXTERNAL_URL`, если это предусмотрено конфигурацией запуска.

`HELPER_SECRET` должен совпадать между Userbot и Helper.

Не публикуйте токены и секреты в GitHub.

## Получение API_ID и API_HASH

1. Откройте Telegram API development tools.
2. Войдите в свой Telegram-аккаунт.
3. Создайте приложение, если его ещё нет.
4. Сохраните `API_ID` и `API_HASH`.

`API_HASH` нельзя публиковать.

## Создание STRING_SESSION с телефона

Для генерации сессии можно использовать Termux.

Пример отдельного файла `generate_session.py`:

```python
from telethon import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("API_ID: "))
api_hash = input("API_HASH: ").strip()

with TelegramClient(StringSession(), api_id, api_hash) as client:
    print("\\n" + "=" * 60)
    print("STRING_SESSION:")
    print("=" * 60)
    print(client.session.save())
    print("=" * 60)
```

Запуск:

```text
python generate_session.py
```

Полученную строку нужно сохранить в Render Environment Variables как
`STRING_SESSION`.

Никому не отправляйте `STRING_SESSION`.

## Создание Helper Bot

1. Откройте BotFather.
2. Создайте Telegram-бота.
3. Получите токен.
4. Укажите токен в `BUTTON_BOT_TOKEN`.
5. Включите Inline Mode для Helper Bot.
6. Если функция проекта использует Inline Feedback, включите и его.

Токен Helper Bot нельзя помещать в публичный репозиторий.

## Настройка Render

Для проекта с `launcher.py`:

**Build Command**

```text
pip install -r requirements.txt
```

**Start Command**

```text
python launcher.py
```

Версия Python должна соответствовать `runtime.txt`.

После запуска откройте Render Logs и убедитесь, что Userbot и Helper успешно
инициализировались и веб-сервис слушает указанный порт.

## Webhook

`launcher.py` получает публичный URL Render из `WEBHOOK_URL` либо из
`RENDER_EXTERNAL_URL` и передаёт его Helper для настройки Telegram Webhook.

Поэтому актуальная архитектура не требует отдельного Render-сервиса только
для Helper.

## Inline Mode

Inline Mode нужен для того, чтобы Userbot мог запросить у Helper результат
по токену и вставить его в нужный чат.

Для callback-кнопок Helper связывает токен, callback ID и
`inline_message_id`, после чего передаёт событие обратно Userbot.

## Безопасность

Никогда не публикуйте в GitHub:

- `API_HASH`;
- `STRING_SESSION`;
- `BUTTON_BOT_TOKEN`;
- `HELPER_SECRET`;
- `WEBHOOK_SECRET`;
- другие секретные значения Environment Variables.

Если секрет был случайно опубликован, его следует заменить/отозвать через
соответствующий сервис.

## Проверка перед загрузкой на GitHub

Перед публикацией проверьте:

1. В коде нет настоящих токенов.
2. В коде нет настоящей `STRING_SESSION`.
3. `API_HASH` не записан в файл.
4. `HELPER_SECRET` не записан в файл.
5. `userbot.py` проходит проверку Python-синтаксиса.
6. `requirements.txt` содержит необходимые зависимости.
7. `runtime.txt` соответствует выбранной версии Python.

Проверка синтаксиса:

```text
python -m py_compile userbot.py
```

## Лицензия

Этот проект распространяется на условиях GNU General Public License v3.0,
если вместе с проектом предоставлен соответствующий текст лицензии.

Без отдельного разрешения автора запрещается выдавать проект или его
производные версии за собственную разработку, а также публично перепубликовать
исходный код или копию репозитория.

При разрешённом распространении необходимо сохранять указание авторства и
условия лицензии.

Полный текст GPLv3 должен находиться в файле `LICENSE`, если он включён в
репозиторий проекта.

## Обратная связь

Для связи с автором используется Telegram-бот:

https://t.me/Channel_feedbackbot

Это бот обратной связи. Не отправляйте через него пароли, токены,
`STRING_SESSION`, `API_HASH`, `HELPER_SECRET` или другие секретные данные.

Автор проекта: **Даниил К.**

## Итог

Актуальная схема проекта:

```text
📱 Телефон / Termux
        │
        ├── API_ID + API_HASH
        └── STRING_SESSION
                │
                ▼
        📦 GitHub
                │
                ▼
        ☁️ Render
        ┌─────────────────────────┐
        │ launcher.py             │
        │ ├── userbot.py         │
        │ └── bot.py             │
        └─────────────────────────┘
                │
                ├── Telegram Userbot
                └── Telegram Helper Bot

Userbot ──► MineEVO
Userbot ──► Helper ──► Inline Message
Helper ──► Callback ──► Userbot ──► MineEVO
```

Golden Userbot 26.3.0 сохраняет основную функциональность предыдущей версии,
а обработка `promo_seen` дополнена подтверждением успешной активации и ручной
командой `.promoseen`.
