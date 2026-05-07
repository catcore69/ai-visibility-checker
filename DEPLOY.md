# Деплой на VPS (Timeweb Cloud)

Подробная пошаговая инструкция по развёртыванию AI Visibility Checker на сервере.

---

## Требования к серверу

- **ОС**: Ubuntu 22.04 LTS
- **RAM**: от 2 GB (рекомендуется 4 GB)
- **CPU**: от 2 ядер
- **Диск**: от 20 GB SSD
- **Порты**: 80, 443 открыты
- **Домен**: настроен A-запись → IP сервера

---

## 1. Подготовка сервера

```bash
# Подключиться по SSH
ssh root@YOUR_SERVER_IP

# Обновить пакеты
apt update && apt upgrade -y

# Установить зависимости
apt install -y curl git ufw fail2ban

# Настроить firewall
ufw allow OpenSSH
ufw allow 80
ufw allow 443
ufw enable

# Создать пользователя (не работать под root)
adduser deploy
usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy
```

---

## 2. Установить Docker

```bash
curl -fsSL https://get.docker.com | sh
usermod -aG docker deploy

# Проверить
docker --version
docker compose version
```

---

## 3. Установить Certbot (SSL)

```bash
apt install -y certbot python3-certbot-nginx
```

---

## 4. Клонировать проект

```bash
su - deploy
git clone <repo-url> ~/ai-visibility-checker
cd ~/ai-visibility-checker
```

---

## 5. Настроить переменные окружения

```bash
cp .env.example .env
nano .env
```

**Обязательно заполнить:**

```env
# Домен (без http/https)
STUDIO_FULL_URL=https://your-domain.ru

# База данных (используйте managed PostgreSQL Timeweb или docker)
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/aivisibility
DATABASE_URL_SYNC=postgresql://user:password@localhost:5432/aivisibility

# Redis
REDIS_URL=redis://redis:6379/0

# API ключи всех 7 моделей
OPENAI_API_KEY=sk-...
YANDEX_API_KEY=...
YANDEX_FOLDER_ID=...
GIGACHAT_CREDENTIALS=...
GEMINI_API_KEY=...
DEEPSEEK_API_KEY=...
PERPLEXITY_API_KEY=...
XMLRIVER_USER=...
XMLRIVER_KEY=...

# SMTP (Timeweb)
SMTP_HOST=smtp.timeweb.ru
SMTP_PORT=465
SMTP_USER=noreply@your-domain.ru
SMTP_PASSWORD=...
FROM_EMAIL=noreply@your-domain.ru
FROM_NAME=Cat Core GEO

# S3 (Timeweb)
S3_ENDPOINT_URL=https://s3.timeweb.cloud
S3_ACCESS_KEY=...
S3_SECRET_KEY=...
S3_BUCKET_NAME=aivisibility-reports
S3_REGION=ru-1

# Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
INTERNAL_API_TOKEN=<случайная строка 32 символа>

# Google Sheets
GOOGLE_SHEETS_SPREADSHEET_ID=...
GOOGLE_SERVICE_ACCOUNT_JSON=credentials/google_service_account.json

# Безопасность
SECRET_KEY=<случайная строка 64 символа>
TURNSTILE_SECRET_KEY=...

# Настройки студии
STUDIO_NAME=Cat Core GEO Studio
STUDIO_EMAIL=hello@your-domain.ru
EXPERT_NAME=Иван Иванов
EXPERT_TITLE=GEO-стратег, Cat Core
CONTACT_TG_BOT=@catcore_geo_bot
CONTACT_TG_BOT_URL=https://t.me/catcore_geo_bot
EXPERT_REVIEW_BEFORE_SEND=true
EXPERT_REVIEW_TIMEOUT_MINUTES=60
```

---

## 6. Добавить Google Service Account

```bash
mkdir -p credentials
# Загрузить JSON-файл сервисного аккаунта
# Способ 1: scp с локальной машины
scp google_service_account.json deploy@YOUR_SERVER_IP:~/ai-visibility-checker/credentials/

# Способ 2: вставить содержимое вручную
nano credentials/google_service_account.json
```

---

## 7. Получить SSL-сертификат

```bash
# Сначала запустить временный nginx для ACME challenge
certbot certonly --standalone -d your-domain.ru -d www.your-domain.ru
```

---

## 8. Настроить Nginx конфиг

В `nginx/nginx.conf` поменяйте `server_name` на ваш домен:

```nginx
server_name your-domain.ru www.your-domain.ru;

ssl_certificate     /etc/letsencrypt/live/your-domain.ru/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/your-domain.ru/privkey.pem;
```

---

## 9. Настроить фронтенд

```bash
# Создать .env.local для фронтенда
cat > frontend/.env.local << EOF
NEXT_PUBLIC_API_URL=https://your-domain.ru
NEXT_PUBLIC_TURNSTILE_SITE_KEY=your_turnstile_site_key
NEXT_PUBLIC_TG_BOT_URL=https://t.me/catcore_geo_bot
NEXT_PUBLIC_STUDIO_EMAIL=hello@your-domain.ru
EOF
```

---

## 10. Запустить в продакшне

```bash
# Собрать и поднять все контейнеры
docker compose -f docker-compose.prod.yml up --build -d

# Проверить что всё запустилось
docker compose -f docker-compose.prod.yml ps

# Логи
docker compose -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.prod.yml logs -f worker
```

---

## 11. Применить миграции БД

```bash
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

---

## 12. Проверить работу

```bash
# Health check
curl https://your-domain.ru/health

# Ожидаемый ответ:
# {"status": "ok"}
```

Откройте браузер: `https://your-domain.ru/proverka`

---

## Автообновление SSL-сертификата

```bash
# Добавить в crontab
crontab -e

# Добавить строку:
0 3 * * * certbot renew --quiet && docker compose -f /home/deploy/ai-visibility-checker/docker-compose.prod.yml exec nginx nginx -s reload
```

---

## Обновление приложения

```bash
cd ~/ai-visibility-checker

# Получить изменения
git pull

# Пересобрать и перезапустить
docker compose -f docker-compose.prod.yml up --build -d

# Применить новые миграции (если есть)
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

---

## Мониторинг и логи

```bash
# Все логи
docker compose -f docker-compose.prod.yml logs -f

# Только воркер
docker compose -f docker-compose.prod.yml logs -f worker

# Только backend
docker compose -f docker-compose.prod.yml logs -f backend

# Статус контейнеров
docker compose -f docker-compose.prod.yml ps

# Использование ресурсов
docker stats
```

---

## Управление Celery

```bash
# Посмотреть активные задачи
docker compose -f docker-compose.prod.yml exec worker celery -A app.celery_app inspect active

# Посмотреть очередь
docker compose -f docker-compose.prod.yml exec worker celery -A app.celery_app inspect reserved

# Перезапустить воркер
docker compose -f docker-compose.prod.yml restart worker
```

---

## Резервное копирование

### База данных
```bash
# Дамп БД
docker compose -f docker-compose.prod.yml exec postgres pg_dump -U postgres aivisibility > backup_$(date +%Y%m%d).sql

# Восстановление
docker compose -f docker-compose.prod.yml exec -i postgres psql -U postgres aivisibility < backup_YYYYMMDD.sql
```

### Файлы .env и credentials
```bash
# Хранить вне репозитория в защищённом месте!
tar czf secrets_backup.tar.gz .env credentials/
```

---

## Типичные проблемы

### PDF не генерируется
```bash
# Проверить что WeasyPrint-зависимости установлены
docker compose -f docker-compose.prod.yml exec backend python -c "import weasyprint; print('OK')"

# Посмотреть логи worker
docker compose -f docker-compose.prod.yml logs worker | grep ERROR
```

### Письма не доходят
```bash
# Проверить SMTP вручную
docker compose -f docker-compose.prod.yml exec backend python -c "
import asyncio, aiosmtplib
async def test():
    await aiosmtplib.send(
        'Test', sender='from@domain.ru', recipients=['to@domain.ru'],
        hostname='smtp.timeweb.ru', port=465, use_tls=True,
        username='from@domain.ru', password='password'
    )
asyncio.run(test())
"
```

### Redis недоступен
```bash
docker compose -f docker-compose.prod.yml exec backend python -c "
import asyncio, redis.asyncio as redis
async def test():
    r = redis.from_url('redis://redis:6379')
    print(await r.ping())
asyncio.run(test())
"
```

### GigaChat ошибка SSL
GigaChat требует российский корневой сертификат. В `gigachat_poller.py` используется `verify=False` — это нормально для MVP. В продакшне можно добавить сертификат Минцифры.

---

## Безопасность в продакшне

- [ ] Установить надёжный `SECRET_KEY` (64+ символов, случайный)
- [ ] Установить `INTERNAL_API_TOKEN` (защита `/internal/` эндпоинтов)
- [ ] Включить Cloudflare Turnstile (`TURNSTILE_SECRET_KEY`)
- [ ] Настроить fail2ban для защиты SSH
- [ ] Регулярно обновлять Docker-образы (`docker compose pull`)
- [ ] Не хранить `.env` в git
- [ ] Ограничить доступ к порту 5432 (PostgreSQL) только внутренней сетью Docker
