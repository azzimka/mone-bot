# 💰 Mone — личный финансовый помощник

> Telegram-бот для контроля расходов с голосовым вводом на русском языке

---

## Что это

**Mone** — это умный Telegram-бот, который помогает отслеживать твои расходы. Просто говоришь ему голосом (или пишешь текстом) что и сколько потратил — он всё записывает, категоризирует и показывает статистику.

Никаких таблиц, никаких сложных приложений. Просто мессенджер, который ты и так открываешь каждый день.

---

## Как пользоваться

### Добавить расход

Отправь голосовое сообщение или напиши текстом:

```
Кофе 25 тысяч
Такси 30к
Обед 80000 сум
Кофе 25к и такси 30к
```

Бот распознает речь, разберёт сумму и категорию, покажет карточку подтверждения. Ты нажимаешь **✅ Верно** — и готово.

### Посмотреть статистику

Используй кнопки внизу экрана или команды:

| Кнопка / Команда | Что показывает |
|---|---|
| 📋 **Расходы за сегодня** | Каждая трата за день + итог |
| 📊 **Расходы за неделю** | Сколько потрачено каждый день (с графиком) |
| `/help` | Справка |

---

## Пример работы

```
Ты:   🎤 «Кофе 25 тысяч, такси 30 тысяч»

Бот:  🎤 Распознано: «Кофе 25 тысяч, такси 30 тысяч»

      1 из 2
      ✅ Распознано:
      📤 Тип: Расход
      💰 Сумма: 25 000 UZS
      📂 Категория: Еда
      📝 Описание: кофе
      [✅ Верно]  [❌ Отменить]

      2 из 2
      ✅ Распознано:
      📤 Тип: Расход
      💰 Сумма: 30 000 UZS
      📂 Категория: Транспорт
      📝 Описание: такси
      [✅ Верно]  [❌ Отменить]
```

---

## Технологии

| Компонент | Технология |
|---|---|
| Платформа | Telegram Bot API |
| Язык | Python 3.12 |
| Фреймворк | aiogram 3 |
| Распознавание речи | Groq Whisper (`whisper-large-v3-turbo`) |
| Понимание текста | Groq LLM (`openai/gpt-oss-20b`) |
| База данных | PostgreSQL 16 |
| ORM | SQLAlchemy 2 (async) |
| Деплой | Docker Compose / DigitalOcean |

---

## Установка и запуск

### 1. Клонируй репозиторий

```bash
git clone <repo-url>
cd cash_control
```

### 2. Создай `.env` файл

```bash
cp .env.example .env
```

Заполни переменные в `.env`:

```env
TELEGRAM_BOT_TOKEN=токен_от_BotFather
GROQ_API_KEY=твой_ключ_с_console.groq.com
DATABASE_URL=postgresql+asyncpg://cashcontrol:пароль@localhost:5432/cashcontrol
DEFAULT_CURRENCY=UZS
```

### 3. Запусти базу данных

```bash
# Через Docker (только PostgreSQL)
docker compose -f docker-compose.local.yml up -d

# Или через Homebrew (macOS)
brew install postgresql@16
brew services start postgresql@16
createdb cashcontrol
psql cashcontrol -c "CREATE USER cashcontrol WITH PASSWORD 'пароль';"
psql cashcontrol -c "GRANT ALL PRIVILEGES ON DATABASE cashcontrol TO cashcontrol;"
```

### 4. Установи зависимости

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 5. Запусти бота

```bash
python -m bot.main
```

---

## Деплой на сервер (DigitalOcean)

```bash
# На сервере (Ubuntu 24.04)
git clone <repo-url> /opt/mone
cd /opt/mone
cp .env.example .env
nano .env  # Вставь токены

# Запуск всего через Docker
docker compose up -d
```

Всё — бот работает в фоне 24/7.

---

## Структура проекта

```
cash_control/
├── bot/
│   ├── handlers/        # Обработчики сообщений и команд
│   │   ├── commands.py  # /start, /today, /week
│   │   ├── voice.py     # Голосовые сообщения
│   │   ├── text.py      # Текстовые сообщения
│   │   └── callbacks.py # Кнопки подтверждения
│   ├── services/        # AI-сервисы
│   │   ├── speech.py    # Распознавание речи (Groq Whisper)
│   │   ├── ai_parser.py # Парсинг трат из текста (LLM)
│   │   └── reports.py   # Форматирование отчётов
│   ├── models/          # Модели базы данных
│   ├── database/        # Подключение к БД и репозитории
│   ├── config.py        # Конфигурация из .env
│   └── main.py          # Точка входа
├── docker-compose.yml        # Продакшн (бот + БД)
├── docker-compose.local.yml  # Разработка (только БД)
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## Что планируется добавить

- [ ] Парсинг SMS-уведомлений от банков (Kapitalbank, Uzcard, Humo)
- [ ] Импорт банковской выписки (CSV/Excel)
- [ ] Лимиты бюджета с уведомлениями
- [ ] Экспорт статистики в Excel
- [ ] Баланс и отчёт за месяц

---

## Лицензия

MIT — используй как хочешь.
