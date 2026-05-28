'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

import { submitCheck, type CheckPayload } from '@/lib/api';
import { getFingerprint } from '@/lib/fingerprint';

declare global {
  interface Window {
    turnstile: {
      render: (container: string | HTMLElement, params: Record<string, unknown>) => string;
      remove: (widgetId: string) => void;
      reset: (widgetId: string) => void;
    };
  }
}

/** Regex для предварительной валидации URL на клиенте. */
const URL_RE = /^(https?:\/\/)?([a-z0-9-]+\.)+[a-z]{2,}(:\d+)?(\/.*)?$/i;

const TURNSTILE_SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY || '';

export default function HeroForm() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [websiteUrl, setWebsiteUrl] = useState('');
  const [brandName, setBrandName] = useState('');
  const [niche, setNiche] = useState('');
  const [competitors, setCompetitors] = useState('');
  const [email, setEmail] = useState('');
  const [hpName, setHpName] = useState(''); // honeypot
  const [consentPersonal, setConsentPersonal] = useState(false);
  const [consentCrossBorder, setConsentCrossBorder] = useState(false);
  const [turnstileToken, setTurnstileToken] = useState('');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const turnstileRef = useRef<HTMLDivElement>(null);
  const widgetIdRef = useRef<string | null>(null);

  // Рендер Cloudflare Turnstile (если ключ задан). Скрипт грузится в layout.tsx.
  useEffect(() => {
    if (!TURNSTILE_SITE_KEY) return;
    let cancelled = false;
    const tryRender = () => {
      if (cancelled) return;
      if (!turnstileRef.current || !window.turnstile) {
        setTimeout(tryRender, 300);
        return;
      }
      if (widgetIdRef.current) return; // уже отрендерен
      widgetIdRef.current = window.turnstile.render(turnstileRef.current, {
        sitekey: TURNSTILE_SITE_KEY,
        callback: (token: string) => setTurnstileToken(token),
        'expired-callback': () => setTurnstileToken(''),
        theme: 'dark',
        size: 'flexible',
      });
    };
    tryRender();
    return () => {
      cancelled = true;
    };
  }, []);

  const turnstileReady = !TURNSTILE_SITE_KEY || !!turnstileToken;

  const canSubmit =
    !!websiteUrl.trim() &&
    !!brandName.trim() &&
    !!niche.trim() &&
    !!email.trim() &&
    consentPersonal &&
    consentCrossBorder &&
    turnstileReady &&
    !loading;

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setError('');

      if (hpName) return; // honeypot — молча уходим

      if (!websiteUrl || !brandName || !niche || !email) {
        setError('Пожалуйста, заполните все обязательные поля.');
        return;
      }

      if (!URL_RE.test(websiteUrl.trim())) {
        setError('Похоже, адрес сайта введён некорректно. Пример: https://example.ru');
        return;
      }

      if (!consentPersonal || !consentCrossBorder) {
        setError('Без обоих согласий мы не можем обработать запрос (требование Закона РБ № 99-З).');
        return;
      }

      if (TURNSTILE_SITE_KEY && !turnstileToken) {
        setError('Подождите, идёт проверка «вы не робот».');
        return;
      }

      setLoading(true);
      try {
        const fingerprintId = await getFingerprint();

        // CSV-конкуренты → массив, очистка, до 5 штук.
        const competitorsList = competitors
          .split(/[,;\n]+/)
          .map((s) => s.trim())
          .filter(Boolean)
          .slice(0, 5);

        const payload: CheckPayload = {
          url: websiteUrl.trim(),
          brand_name: brandName.trim(),
          niche: niche.trim(),
          email: email.trim().toLowerCase(),
          client_competitors: competitorsList.length ? competitorsList : undefined,
          consent_personal_data: consentPersonal,
          consent_cross_border: consentCrossBorder,
          turnstile_token: turnstileToken,
          fingerprint_id: fingerprintId,
          hp_name: hpName,
          utm_source: searchParams.get('utm_source') || undefined,
          utm_medium: searchParams.get('utm_medium') || undefined,
          utm_campaign: searchParams.get('utm_campaign') || undefined,
        };

        const result = await submitCheck(payload);
        router.push(
          `/proverka/verify-email?id=${result.report_id}&email=${encodeURIComponent(email)}`,
        );
      } catch (err: unknown) {
        const axiosErr = err as {
          response?: { data?: { detail?: string | unknown[] } };
          message?: string;
        };
        const detail = axiosErr.response?.data?.detail;
        if (typeof detail === 'string') {
          setError(detail);
        } else if (Array.isArray(detail)) {
          setError(
            (detail as { msg?: string }[])
              .map((d) => d.msg || '')
              .filter(Boolean)
              .join('; ') || 'Ошибка валидации.',
          );
        } else {
          setError('Что-то пошло не так. Попробуйте ещё раз.');
        }
        // Сбрасываем капчу — токен одноразовый.
        if (widgetIdRef.current && window.turnstile) {
          window.turnstile.reset(widgetIdRef.current);
          setTurnstileToken('');
        }
      } finally {
        setLoading(false);
      }
    },
    [
      websiteUrl,
      brandName,
      niche,
      competitors,
      email,
      hpName,
      consentPersonal,
      consentCrossBorder,
      turnstileToken,
      router,
      searchParams,
    ],
  );

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
      {/* Honeypot */}
      <div className="hp-field" aria-hidden="true">
        <input
          type="text"
          name="name"
          value={hpName}
          onChange={(e) => setHpName(e.target.value)}
          tabIndex={-1}
          autoComplete="off"
        />
      </div>

      <Field
        id="website_url"
        label="Сайт вашей компании *"
        type="url"
        placeholder="https://example.ru"
        value={websiteUrl}
        onChange={setWebsiteUrl}
        required
        helper="Введите адрес вашего сайта (не профиля на Авито, ВК или маркетплейсе)."
      />

      <Field
        id="brand_name"
        label="Название бренда *"
        type="text"
        placeholder="Например: Сбербанк, Манома, Notion"
        value={brandName}
        onChange={setBrandName}
        required
      />

      <Field
        id="niche"
        label="Ниша / тематика бизнеса *"
        type="text"
        placeholder="Например: усадьба на Дальнем Востоке, SaaS для HR"
        value={niche}
        onChange={setNiche}
        required
      />

      {/* Срочный фикс 3.4 — поле конкурентов сделано заметным (предохранитель
          против нерелевантных конкурентов для регионального бизнеса). */}
      <div className="flex flex-col gap-1.5 rounded-xl border border-accent-700/40 bg-accent-900/10 p-4">
        <label htmlFor="competitors" className="text-sm font-medium text-brand-textBright">
          Знаете 2–3 конкурентов? Впишите — отчёт будет заметно точнее
        </label>
        <input
          id="competitors"
          type="text"
          placeholder="Например: Шепалово, Уссурийская заводь, Манома"
          value={competitors}
          onChange={(e) => setCompetitors(e.target.value)}
          className="input-field"
        />
        <p className="text-xs text-brand-muted">
          Особенно важно для регионального и нишевого бизнеса. Если не укажете —
          подберём по поисковой выдаче вашей ниши и региона.
        </p>
      </div>

      <Field
        id="email"
        label="Email для получения отчёта *"
        type="email"
        placeholder="you@company.com"
        value={email}
        onChange={setEmail}
        required
        helper="Отчёт будет готов через 3–7 минут. Спам не рассылаем."
      />

      {/* Этап 1.4 ТЗ — два РАЗДЕЛЬНЫХ чекбокса согласия. Оба обязательны. */}
      <div className="card-surface p-4 flex flex-col gap-3 mt-2">
        <ConsentCheckbox
          id="consent_personal_data"
          checked={consentPersonal}
          onChange={setConsentPersonal}
        >
          Согласен с{' '}
          <a
            href="/privacy"
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent-400 hover:underline"
          >
            политикой обработки персональных данных
          </a>
          .
        </ConsentCheckbox>

        <ConsentCheckbox
          id="consent_cross_border"
          checked={consentCrossBorder}
          onChange={setConsentCrossBorder}
        >
          Согласен на трансграничную передачу моих персональных данных в Российскую
          Федерацию и США для обработки сервисами хостинга, CRM, аналитики и языковых
          моделей (полный список —{' '}
          <a
            href="/privacy"
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent-400 hover:underline"
          >
            в политике
          </a>
          ).
        </ConsentCheckbox>
      </div>

      {/* Cloudflare Turnstile (рендерится, если задан NEXT_PUBLIC_TURNSTILE_SITE_KEY) */}
      {TURNSTILE_SITE_KEY && <div ref={turnstileRef} className="mt-1" />}

      {error && (
        <div className="border border-accent-700/60 bg-accent-900/30 rounded-xl px-4 py-3 text-sm text-accent-200">
          {error}
        </div>
      )}

      <button type="submit" disabled={!canSubmit} className="btn-primary mt-2 w-full">
        {loading ? (
          <span className="inline-flex items-center justify-center gap-2">
            <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            Отправляем…
          </span>
        ) : (
          'Проверить бесплатно'
        )}
      </button>
    </form>
  );
}

/** Поле формы в стиле дизайн-системы. */
function Field(props: {
  id: string;
  label: string;
  type: string;
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
  required?: boolean;
  helper?: string;
}) {
  const { id, label, type, placeholder, value, onChange, required, helper } = props;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-brand-text">
        {label}
      </label>
      <input
        id={id}
        type={type}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        className="input-field"
      />
      {helper && <p className="text-xs text-brand-muted">{helper}</p>}
    </div>
  );
}

function ConsentCheckbox(props: {
  id: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  children: React.ReactNode;
}) {
  const { id, checked, onChange, children } = props;
  return (
    <label
      htmlFor={id}
      className="flex items-start gap-3 cursor-pointer text-sm text-brand-text leading-relaxed"
    >
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 w-4 h-4 accent-accent-500 flex-shrink-0 cursor-pointer"
        required
      />
      <span>{children}</span>
    </label>
  );
}
