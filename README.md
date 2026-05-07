# AI Visibility Checker

Бесплатный инструмент-лидмагнит от **Cat Core GEO Studio**: проверяет, как часто ИИ-ассистенты (ChatGPT, YandexGPT, GigaChat, Gemini, Perplexity, DeepSeek, Алиса) упоминают бренд клиента по сравнению с 5 конкурентами. Результат — PDF-отчёт с AI Visibility Score и персональными рекомендациями.

---

## Стек

| Слой       | Технологии                                                        |
|------------|-------------------------------------------------------------------|
| Backend    | Python 3.11, FastAPI, Celery + Redis, SQLAlchemy 2.0, PostgreSQL 17 |
| PDF        | WeasyPrint, Matplotlib, Jinja2                                    |
| Frontend   | Next.js 14, TypeScript, Tailwind CSS                              |
| Хранение   | Timeweb Cloud S3 (boto3)                                          |
| Email      | aiosmtplib → smtp.timeweb.ru                                      |
| CRM        | Google Sheets (gspread) + Telegram Bot                            |

---

## Быстрый старт (локальная разработка)

### 1. Требования

- Docker Desktop ≥ 24
- Python 3.11 (для запуска без Docker)
- Node.js 20+ (для фронтенда без Docker)

### 2. Клонировать репозиторий

```bash
git clone <repo-url> ai-visibility-checker
cd ai-visibility-checker
```

### 3. Настроить переменные окружения

```bash
cp .env.example .env
```

Откройте `.env` и заполните **обязательные** поля:

| Переменная                 | Описание                                              |
|----------------------------|-------------------------------------------------------|
| `OPENAI_API_KEY`           | API-ключ OpenAI (для ChatGPT и LLM-анализа)          |
| `YANDEX_API_KEY`           | IAM-токен или API-ключ Yandex Cloud                  |
| `YANDEX_FOLDER_ID`         | ID каталога в Yandex Cloud                           |
| `GIGACHAT_CREDENTIALS`     | Base64 ClientID:ClientSecret от Сбера                |
| `GEMINI_API_KEY`           | API-ключ Google AI Studio                            |
| `DEEPSEEK_API_KEY`         | API-ключ DeepSeek                                    |
| `PERPLEXITY_API_KEY`       | API-ключ Perplexity AI                               |
| `XMLRIVER_USER`            | Логин XMLRiver (для Яндекс Нейро / Алиса)            |
| `XMLRIVER_KEY`             | API-ключ XMLRiver                                    |
| `SMTP_HOST`                | smtp.timeweb.ru                                      |
| `SMTP_USER`                | Email-адрес отправителя                              |
| `SMTP_PASSWORD`            | Пароль почты                                         |
| `FROM_EMAIL`               | Адрес в заголовке From                               |
| `S3_ENDPOINT_URL`          | URL эндпоинта Timeweb S3                             |
| `S3_ACCESS_KEY`            | Access Key от Timeweb S3                             |
| `S3_SECRET_KEY`            | Secret Key от Timeweb S3                             |
| `S3_BUCKET_NAME`           | Имя бакета                                           |
| `TELEGRAM_BOT_TOKEN`       | Токен Telegram-бота для уведомлений                  |
| `TELEGRAM_CHAT_ID`         | Chat ID куда слать уведомления                       |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | ID Google Sheets таблицы (CRM)               |
| `SECRET_KEY`               | Случайная строка 32+ символа (JWT)                   |

> Минимум для локального тестирования: `OPENAI_API_KEY` + `SECRET_KEY` + SMTP.  
> Остальные модели можно отключить через `ENABLED_MODELS` в `.env`.

### 4. Запустить через Docker Compose

```bash
docker compose up --build
```

Это поднимет:
- `postgres:17-alpine` на порту 5432
- `redis:7-alpine` на порту 6379
- `backend` (FastAPI + uvicorn) на порту 8000
- `worker` (Celery worker)
- `beat` (Celery beat — расписание)

### 5. Применить миграции БД

```bash
docker compose exec backend alembic upgrade head
```

### 6. Запустить фронтенд

```bash
cd frontend
npm install
npm run dev
```

Фронтенд откроется на [http://localhost:3000](http://localhost:3000).

---

## Запуск без Docker (только backend)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Нужен запущенный PostgreSQL и Redis (см. docker-compose.yml для конфигурации)
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

**Worker и beat (в отдельных терминалах):**

```bash
celery -A app.celery_app worker -l info -c 2
celery -A app.celery_app beat -l info
```

---

## Структура проекта

```
ai-visibility-checker/
├── backend/
│   ├── app/
│   │   ├── api/v1/routes.py       # FastAPI эндпоинты
│   │   ├── core/
│   │   │   ├── pipeline.py        # Главный оркестратор
│   │   │   ├── analyzer.py        # Двухэтапный анализ упоминаний
│   │   │   ├── scorer.py          # AI Visibility Score
│   │   │   ├── report_builder.py  # WeasyPrint PDF + Matplotlib
│   │   │   └── llm_prompts.py     # Промпты для LLM
│   │   ├── llm_pollers/           # 7 поллеров моделей
│   │   ├── db/models/             # SQLAlchemy модели
│   │   ├── email/                 # aiosmtplib + шаблоны
│   │   ├── integrations/          # Telegram, Google Sheets
│   │   ├── storage/               # S3-клиент
│   │   ├── tasks/                 # Celery-задачи
│   │   └── utils/                 # Rate limiter, URL-нормализатор
│   ├── templates/
│   │   ├── report.html            # Главный PDF-шаблон
│   │   └── report_partials/       # 7 частичных шаблонов
│   ├── alembic/                   # Миграции БД
│   └── tests/                     # pytest-тесты
├── frontend/
│   ├── app/
│   │   ├── proverka/page.tsx      # Форма проверки
│   │   ├── proverka/verify-email/ # Страница подтверждения email
│   │   └── otchet/[id]/           # Статус + просмотр отчёта
│   ├── components/                # React-компоненты
│   └── lib/                       # API-клиент, утилиты
├── nginx/nginx.conf
├── docker-compose.yml
├── docker-compose.prod.yml
└── .env.example
```

---

## API эндпоинты

| Метод  | Путь                              | Описание                              |
|--------|-----------------------------------|---------------------------------------|
| POST   | `/api/v1/check`                   | Создать заявку на проверку            |
| GET    | `/api/v1/verify/{token}`          | Подтвердить email                     |
| GET    | `/api/v1/report/{id}/status`      | Статус генерации                      |
| GET    | `/api/v1/report/{id}`             | Полные данные отчёта (JSON)           |
| GET    | `/api/v1/report/{id}/pdf`         | Pre-signed URL на PDF                 |
| POST   | `/api/v1/report/{id}/cta`         | Трекинг CTA-клика                     |
| POST   | `/api/v1/check/{id}/resend-email` | Повторная отправка письма             |
| POST   | `/api/v1/internal/report/{id}/action` | Экспертное действие (internal) |
| GET    | `/health`                         | Health-check                          |

---

## Запуск тестов

```bash
cd backend
pip install pytest pytest-asyncio pytest-cov aiosqlite httpx
pytest tests/ -v --tb=short
```

С покрытием:

```bash
pytest tests/ --cov=app --cov-report=term-missing
```

---

## Переменные окружения — полный список

Смотрите `.env.example` — там все переменные с описаниями и значениями по умолчанию.

---

## Деплой на VPS

Подробная инструкция — в файле [`DEPLOY.md`](./DEPLOY.md).
