from typing import Annotated
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # === App ===
    APP_ENV: str = "development"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me"
    INTERNAL_API_TOKEN: str = "change-me"

    # === Database ===
    DATABASE_URL: str
    DATABASE_URL_SYNC: str = ""

    # === Redis / Celery ===
    REDIS_URL: str = "redis://redis:6379/0"
    CELERY_BROKER_URL: str = "redis://redis:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/2"

    # === LLM APIs ===
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://yellow-paper-e50f.kitten-69.workers.dev/v1"

    # === Модели по задачам (Итерация-3, Задача 5) ===
    # Дефолт = текущая gpt-4o-mini (нулевое изменение поведения). Фаундер может
    # поднять MODEL_NICHE до gpt-4.1/gpt-4o в .env — точнее определяет нишу и
    # стабильнее между прогонами. Остальные языковые задачи mini тянет.
    MODEL_NICHE: str = "gpt-4o-mini"        # определение ниши из контента (фактчувствительно)
    MODEL_EXTRACTION: str = "gpt-4o-mini"   # извлечение брендов/компаний из текста
    MODEL_TEXT: str = "gpt-4o-mini"         # группировка запросов, оформление рекомендаций
    MODEL_ANALYSIS: str = "gpt-4o-mini"     # анализ упоминаний/тональности

    # Рендер сайтов через headless-браузер (Playwright). По умолчанию OFF —
    # образ не раздуваем. Включать только после подготовки Docker-образа с браузерами.
    USE_PLAYWRIGHT: bool = False
    GEMINI_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    PERPLEXITY_API_KEY: str = ""
    YANDEX_API_KEY: str = ""
    YANDEX_FOLDER_ID: str = ""
    GIGACHAT_AUTH_KEY: str = ""

    # === XMLRiver ===
    XMLRIVER_USER: str = ""
    XMLRIVER_KEY: str = ""
    XMLRIVER_REGION_RU: str = "213"
    XMLRIVER_REGION_BY: str = "157"

    # === Pipeline ===
    # Этап 2.4 ТЗ: "alisa" заменён на "yandex_ai_search" (честное имя XMLRiver SERP).
    ENABLED_MODELS: str = "chatgpt,yandexgpt,yandex_ai_search,gigachat,gemini,deepseek,perplexity"
    # Этап 1.3 ТЗ: снижено с 15 до 10 (4 рек / 3 срав / 2 проб / 1 транз)
    PROMPTS_PER_REPORT: int = 10
    COMPETITORS_PER_REPORT: int = 5
    CACHE_TTL_DAYS: int = 7
    DAILY_REPORT_LIMIT: int = 20

    # === Срочные фиксы: дедуп и лимиты на запуск анализа ===
    # Сколько дней переиспользуем готовый отчёт по тому же домену (не пересчитываем).
    REPORT_REUSE_DAYS: int = 30
    # Жёсткие лимиты на РЕАЛЬНЫЕ запуски (защита от скрутки денег на API).
    MAX_ANALYSES_PER_EMAIL_PER_DAY: int = 2
    MAX_ANALYSES_PER_IP_PER_DAY: int = 5
    MAX_ANALYSES_PER_IP_PER_HOUR: int = 3

    # === Rate limits ===
    RATE_LIMIT_PER_DOMAIN_COUNT: int = 2
    RATE_LIMIT_PER_DOMAIN_BRAND_DAYS: int = 30
    RATE_LIMIT_PER_EMAIL_DAYS: int = 30
    RATE_LIMIT_PER_FINGERPRINT_DAYS: int = 30
    RATE_LIMIT_PER_IP_HOURS: int = 24
    RATE_LIMIT_PER_VPN_DAYS: int = 90

    # === Per-model rate limits (RPM) ===
    OPENAI_MAX_RPM: int = 400
    GEMINI_MAX_RPM: int = 12
    DEEPSEEK_MAX_RPM: int = 60
    YANDEX_MAX_RPM: int = 100
    GIGACHAT_MAX_RPM: int = 50
    PERPLEXITY_MAX_RPM: int = 50
    # Этап 2.4: переименовано из ALISA_MAX_RPM. Старое имя env-переменной
    # сохраняем через alias ниже — чтобы prod не упал, пока не обновят .env.
    YANDEX_AI_SEARCH_MAX_RPM: int = 100

    # === Celery ===
    CELERY_WORKER_CONCURRENCY: int = 2
    CELERY_TASK_TIME_LIMIT: int = 600

    # Жёсткий таймаут на ОДИН вызов LLM-модели (сек). Защита от зависшего
    # HTTP-запроса, который морозит весь опрос (asyncio.gather ждёт вечно →
    # отчёт навсегда застревает на polling_models). См. llm_pollers/base.py.
    LLM_CALL_TIMEOUT: int = 45

    # === S3 ===
    S3_ENDPOINT_URL: str = "https://s3.timeweb.cloud"
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_BUCKET: str = "ai-visibility-reports"
    S3_REGION: str = "ru-1"

    # === Email ===
    SMTP_HOST: str = "smtp.timeweb.ru"
    SMTP_PORT: int = 465
    SMTP_USER: str = "noreply@catcore.ru"
    SMTP_PASSWORD: str = ""
    FROM_EMAIL: str = "noreply@catcore.ru"
    SUPPORT_EMAIL: str = "support@catcore.ru"
    CONTACT_EMAIL: str = "info@catcore.ru"

    # === Cloudflare Turnstile ===
    TURNSTILE_SITE_KEY: str = ""
    TURNSTILE_SECRET_KEY: str = ""

    # === IP Quality ===
    IPAPI_KEY: str = ""

    # === Sentry ===
    SENTRY_DSN: str = ""

    # === Студия и эксперт ===
    EXPERT_NAME: str = "[EXPERT_NAME]"
    EXPERT_FIRST_NAME: str = "[EXPERT_FIRST_NAME]"
    EXPERT_LAST_NAME: str = "[EXPERT_LAST_NAME]"
    EXPERT_TITLE: str = "[EXPERT_TITLE]"
    EXPERT_PHOTO_URL: str = "/expert.jpg"
    EXPERT_BIO_SHORT: str = "[EXPERT_BIO_SHORT]"

    STUDIO_NAME: str = "Cat Core"
    STUDIO_NAME_FULL: str = "Cat Core — студия GEO-продвижения"
    STUDIO_DOMAIN: str = "catcore.ru"
    STUDIO_FULL_URL: str = "https://catcore.ru"
    STUDIO_LOGO_URL: str = "/logo.svg"
    STUDIO_FOUNDED_YEAR: int = 2025
    STUDIO_CITY: str = "Минск"
    STUDIO_COUNTRY_CODE: str = "BY"

    CONTACT_TG_BOT: str = "@catcore_sitebot"
    CONTACT_TG_BOT_URL: str = "https://t.me/catcore_sitebot"

    # === Пакеты услуг (Этап 3 ТЗ, страница 7 PDF) ===
    # Цены зафиксированы по регионам (Итерация-2, Б2). НЕ автоконвертация по курсу —
    # курс плавает, цена услуги стабильна. РБ → BYN, РФ/прочее → ₽.
    PACKAGE_DORABOTKA_PRICE_FROM: str = "150 000"
    PACKAGE_FULL_SITE_PRICE_FROM: str = "350 000"
    PACKAGE_DORABOTKA_PRICE_FROM_BYN: str = "3 500"
    PACKAGE_FULL_SITE_PRICE_FROM_BYN: str = "9 900"
    PACKAGE_GROWTH_PROMISE_POINTS: int = 15  # рост Score за 90 дней

    # === Логика страницы 6 «Почему так получается» (Итерация-2, А2) ===
    # Если максимальный Presence среди конкурентов < этого порога — ниша «свободна»
    # (ИИ ещё не выбрал фаворита), показываем ветку «открытое окно», а не «догони лидера».
    NICHE_OPEN_PRESENCE_MAX: int = 30
    # Если есть конкурент с Presence выше этого — точно «догони лидера» (сильный игрок).
    NICHE_STRONG_LEADER_PRESENCE: int = 50

    # === Воспроизводимость (Итерация-2, Б1) ===
    # В пределах скольки дней повторный анализ того же домена берёт ту же нишу
    # и тех же конкурентов (детерминированность для мониторинга динамики).
    NICHE_REUSE_DAYS: int = 90

    # === Telegram ===
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_NOTIFY_CHAT_ID: str = ""
    # Прокси для api.telegram.org, если провайдер блокирует прямой доступ.
    # Формат httpx: "http://user:pass@host:port" (для socks5 нужен httpx[socks]).
    TELEGRAM_PROXY_URL: str = ""
    # Альтернатива прокси — relay через Cloudflare Worker (бесплатно):
    # деплоим worker, который форвардит к api.telegram.org, и подставляем его URL.
    # Пример: https://tg-relay.username.workers.dev
    # Подробнее: см. infra/cloudflare-workers/telegram-relay.js
    TELEGRAM_API_BASE: str = "https://api.telegram.org"

    # === Workflow эксперта ===
    EXPERT_REVIEW_BEFORE_SEND: bool = True
    EXPERT_REVIEW_TIMEOUT_MINUTES: int = 30

    # === Google Sheets ===
    GOOGLE_SHEETS_CREDENTIALS_PATH: str = "./credentials/google_service_account.json"
    GOOGLE_SHEETS_SPREADSHEET_ID: str = ""

    # Bitrix24 убран: на бесплатном тарифе нет ни REST API (вебхуки/локальные
    # приложения недоступны), ни CRM-формы. CRM-роль выполняет Google Sheets,
    # заявки на разговор собирает наша форма /zapis-na-razgovor → Telegram.

    @property
    def enabled_models_list(self) -> list[str]:
        return [m.strip() for m in self.ENABLED_MODELS.split(",") if m.strip()]

    @property
    def model_rate_limits(self) -> dict[str, int]:
        return {
            "chatgpt": self.OPENAI_MAX_RPM,
            "yandexgpt": self.YANDEX_MAX_RPM,
            "yandex_ai_search": self.YANDEX_AI_SEARCH_MAX_RPM,
            "gigachat": self.GIGACHAT_MAX_RPM,
            "gemini": self.GEMINI_MAX_RPM,
            "deepseek": self.DEEPSEEK_MAX_RPM,
            "perplexity": self.PERPLEXITY_MAX_RPM,
        }


settings = Settings()
