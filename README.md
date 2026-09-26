```This file is part of Golden Userbot.
Licensed under the GNU General Public License v3.0.

You may redistribute and/or modify this file under the terms of the
GNU General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

This file is distributed WITHOUT ANY WARRANTY; without even the implied
warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the LICENSE file for the full license text. ``` 

# Golden Userbot 26.3.0

Golden Userbot — Telegram Userbot с дополнительным Helper Bot для работы с inline-сообщениями и кнопками.

Проект предназначен для запуска на Render как один Web Service.

## Возможности

### ⚙️ Основные команды

- `.work` — выбрать рабочий чат.
- `.repeat` — повторить сообщение указанное количество раз с заданным интервалом.
- `.stoprepeat` — остановить повторение.
- `.calc` — калькулятор.
- `.tc` — получить курс ресурсов.
- `.tcset` — настроить чат и сообщение с шаблоном курса.
- `.lm` — управление функцией LM.
- `.lmpause` — поставить LM на паузу.
- `.lmresume` — продолжить LM.
- `.lmstop` — остановить LM.
- `.lchk` — проверить состояние LM.
- `.thxsource` — выбрать источник для автоматических благодарностей.
- `.thxoff` — отключить автоматические благодарности.

### 🎆 MineEVO

Команда `.evo` получает данные MineEVO и отправляет результат через Helper Bot с inline-сообщением и кнопками.

Если ответить на такое inline-сообщение, Userbot передаст ответ обратно в соответствующее сообщение MineEVO.

### 🔗 Inline-кнопки

Команда `.urlbtn` позволяет создавать сообщения с inline-кнопками и URL.

### 📈 Курсы ресурсов

Команда `.tc` поддерживает получение курса одного или двух ресурсов.

Для одного ресурса результат отображается с заголовком текущего курса и сворачиваемой цитатой.

Для двух ресурсов результат выводится обычным текстом.

### 📨 Сообщения

Обычные команды редактируют исходное сообщение команды и превращают его в результат.

Команды `.evo` и `.urlbtn` используют отдельное inline-сообщение Helper Bot.

### 🔄 Автоматические функции

- автоматическая проверка промокодов;
- автоматические благодарности;
- повторение сообщений;
- LM-функции;
- работа с MineEVO;
- HTTP/Webhook-сервер для работы Telegram Bot API.

## 📁 Структура проекта

```text
Golden-userbot/
├── Golden_Userbot.py
├── userbot.py
├── bot.py
├── requirements.txt
├── runtime.txt
└── README.md
```

### Файлы

**Golden_Userbot.py** — основной файл запуска проекта.

**userbot.py** — логика Golden Userbot и его команд.

**bot.py** — Helper Bot для inline-сообщений, кнопок и callback-запросов.

**requirements.txt** — необходимые Python-библиотеки.

**runtime.txt** — версия Python.

## 🔑 Переменные окружения

Для работы проекта необходимо добавить переменные в Render.

### Обязательные

```text
API_ID
API_HASH
STRING_SESSION
BUTTON_BOT_TOKEN
HELPER_SECRET
```

### Дополнительные (Добавлять не нужно) 

```text
THX_BOT
LM_PROBE_SUM
WEBHOOK_URL
WEBHOOK_SECRET
PORT
```

`PORT` обычно предоставляет Render автоматически.

### API_ID и API_HASH

Получить их можно на:

https://my.telegram.org

После создания приложения Telegram выдаст:

```text
API_ID
API_HASH
```

### STRING_SESSION

`STRING_SESSION` — строковая сессия Telegram-аккаунта, под которым работает Userbot.

Получить её можно с помощью скрипта генерации StringSession через Termux.

Никому не передавайте свою `STRING_SESSION`.

### BUTTON_BOT_TOKEN

Токен Helper Bot, созданного через @BotFather.

### HELPER_SECRET

Секретный ключ для внутренней связи Userbot и Helper Bot.

Можно создать случайную длинную строку, например:

```text
a8f3K2m9Q7xL4p6Z1n5R
```

## 🤖 Настройка Helper Bot

Перед запуском необходимо:

1. Создать бота через `@BotFather`.
2. Получить его токен.
3. Включить **Inline Mode**.
4. При необходимости включить **Inline Feedback** на 100%.
5. Добавить токен в Render в переменную:

```text
BUTTON_BOT_TOKEN
```

## 🚀 Запуск на Render

Создайте новый **Web Service** и подключите GitHub-репозиторий проекта.

### Build Command

```text
pip install -r requirements.txt
```

### Start Command

```text
python Golden_Userbot.py
```

### Runtime

В проекте уже указан файл:

```text
runtime.txt
```

с версией:

```text
python-3.11.9
```

## 🌐 Webhook

Render должен предоставить публичный адрес Web Service.

Можно использовать:

```text
WEBHOOK_URL
```

Если `WEBHOOK_URL` не указана, проект использует адрес Render, если он доступен через переменную `RENDER_EXTERNAL_URL`.

## 🔒 Безопасность

Никому не передавайте:

- `STRING_SESSION`;
- `API_HASH`;
- `BUTTON_BOT_TOKEN`;
- `HELPER_SECRET`.

Все секретные данные должны храниться в **Environment Variables** Render, а не в GitHub.

## 🛠 Требования

- Python 3.11.9
- Telegram-аккаунт
- Telegram API ID и API Hash
- Helper Bot
- Render Web Service

## 📜 Лицензия

Проект предоставляется для личного использования.

### ✅ Разрешено

- Использовать проект в личных целях.
- Запускать проект на собственном аккаунте.
- Настраивать проект под свои нужды без распространения исходного кода.

### ❌ Запрещено

- Изучать, копировать или распространять исходный код проекта.
- Копировать проект полностью или частично.
- Создавать копии или производные проекты на основе исходного кода.
- Перепродавать проект или его части.
- Публиковать исходный код или отдельные файлы проекта.
- Выдавать проект или его части за собственную разработку.
- Удалять информацию об авторстве.
- Использовать проект для нарушения законодательства или правил Telegram.

## 📩 Обратная связь

Если вы нашли ошибку, столкнулись с проблемой или хотите предложить улучшение, свяжитесь с автором проекта:

🔗 [https://t.me/Channel_feedbackbot](https://t.me/Channel_feedbackbot?start=_tgr_0u0va0xjNTAy)

«💬 Это Telegram-бот для связи с автором проекта.
Не пугайтесь того, что это бот — это обычный и удобный способ связаться со мной, сохраняя конфиденциальность в интернете.

В боте нет рекламы и ничего лишнего — он создан исключительно для связи, предложений и обратной связи.»

⚠️ Не отправляйте через бота пароли, токены, "STRING_SESSION" и другие конфиденциальные данные.