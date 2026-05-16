/**
 * Cloudflare Worker — relay для api.telegram.org.
 *
 * Зачем: некоторые провайдеры (Timeweb RU и пр.) режут прямой выход к Telegram.
 * Cloudflare Workers ходят к Telegram спокойно и бесплатно (100k req/день).
 *
 * Развёртывание (~5 минут):
 *
 *   1. https://dash.cloudflare.com → Workers & Pages → "Create application"
 *      → "Create Worker" → дай имя, например `tg-relay`.
 *   2. Нажми "Edit code", удали дефолтный код, вставь содержимое этого файла.
 *      Жми "Deploy".
 *   3. Cloudflare покажет URL: https://tg-relay.<твой-username>.workers.dev
 *      Это и есть твой TELEGRAM_API_BASE.
 *   4. На сервере в .env добавь:
 *      TELEGRAM_API_BASE=https://tg-relay.<твой-username>.workers.dev
 *   5. Перезапусти контейнеры и зарегистрируй webhook:
 *      docker compose -f docker-compose.prod.yml up -d --force-recreate backend worker beat
 *      docker compose -f docker-compose.prod.yml exec backend \
 *          python -m scripts.set_telegram_webhook https://catcore.ru
 *
 * Безопасность: relay не хранит токен. Токен передаётся в каждом URL
 * (`/bot<TOKEN>/<method>`), как и у самого Telegram. Worker просто проксирует
 * запрос. Постороннему, кто знает URL relay, всё равно нужен сам токен бота.
 *
 * Опционально: можно дополнительно ограничить relay только своим IP-адресом
 * VPS — раскомментируй блок ALLOWED_IPS ниже.
 */

const TG_HOST = "api.telegram.org";

// Раскомментируй и впиши IP своего VPS, если хочешь дополнительно ограничить доступ:
// const ALLOWED_IPS = ["123.45.67.89"];

export default {
  async fetch(request) {
    // (опционально) проверка IP
    // if (typeof ALLOWED_IPS !== "undefined") {
    //   const ip = request.headers.get("cf-connecting-ip");
    //   if (!ALLOWED_IPS.includes(ip)) {
    //     return new Response("Forbidden", { status: 403 });
    //   }
    // }

    const url = new URL(request.url);
    // Перенаправляем тот же путь и query на api.telegram.org
    const upstream = `https://${TG_HOST}${url.pathname}${url.search}`;

    // Пересобираем заголовки, убирая Cloudflare-специфичные
    const headers = new Headers(request.headers);
    headers.delete("host");
    headers.delete("cf-connecting-ip");
    headers.delete("cf-ipcountry");
    headers.delete("cf-ray");
    headers.delete("cf-visitor");
    headers.delete("x-forwarded-for");
    headers.delete("x-forwarded-proto");
    headers.delete("x-real-ip");

    const init = {
      method: request.method,
      headers,
      redirect: "follow",
    };
    if (request.method !== "GET" && request.method !== "HEAD") {
      init.body = request.body;
    }

    try {
      const resp = await fetch(upstream, init);
      // Возвращаем как есть — Telegram сам решает Content-Type/статус
      return new Response(resp.body, {
        status: resp.status,
        statusText: resp.statusText,
        headers: resp.headers,
      });
    } catch (err) {
      return new Response(
        JSON.stringify({ ok: false, relay_error: String(err) }),
        { status: 502, headers: { "content-type": "application/json" } }
      );
    }
  },
};
