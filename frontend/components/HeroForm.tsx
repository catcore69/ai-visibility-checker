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

  // Задача 5.1: только URL + email. Бренд и ниша определяются парсингом сайта.
  const [websiteUrl, setWebsiteUrl] = useState('');
  const [email, setEmail] = useState('');
  const [competitors, setCompetitors] = useState(''); // ссылки, по одной на строку
  const [hpName, setHpName] = useState(''); // honeypot
  const [consentPersonal, setConsentPersonal] = useState(false);
  const [consentCrossBorder, setConsentCrossBorder] = useState(false);
  const [turnstileToken, setTurnstileToken] = useState('');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const turnstileRef = useRef<HTMLDivElement>(null);
  const widgetIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!TURNSTILE_SITE_KEY) return;
    let cancelled = false;
    const tryRender = () => {
      if (cancelled) return;
      if (!turnstileRef.current || !window.turnstile) {
        setTimeout(tryRender, 300);
        return;
      }
      if (widgetIdRef.current) return;
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
    !!email.trim() &&
    consentPersonal &&
    consentCrossBorder &&
    turnstileReady &&
    !loading;

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setError('');

      if (hpName) return; // honeypot

      if (!websiteUrl || !email) {
        setError('Заполните адрес сайта и email.');
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

        // Задача 5.2: конкуренты — ССЫЛКИ (или названия), по одной на строку, до 5.
        const competitorsList = competitors
          .split(/[\n,;]+/)
          .map((s) => s.trim())
          .filter(Boolean)
          .slice(0, 5);

        const payload: CheckPayload = {
          url: websiteUrl.trim(),
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
        if (result.status === 'completed') {
          router.push(`/otchet/${result.report_id}?reused=1`);
        } else {
          router.push(
            `/proverka/verify-email?id=${result.report_id}&email=${encodeURIComponent(email)}`,
          );
        }
      } catch (err: unknown) {
        const axiosErr = err as { response?: { data?: { detail?: string | unknown[] } } };
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
        if (widgetIdRef.current && window.turnstile) {
          window.turnstile.reset(widgetIdRef.current);
          setTurnstileToken('');
        }
      } finally {
        setLoading(false);
      }
    },
    [websiteUrl, email, competitors, hpName, consentPersonal, consentCrossBorder, turnstileToken, router, searchParams],
  );

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
      {/* Honeypot */}
      <div className="hp-field" aria-hidden="true">
        <input type="text" name="name" value={hpName} onChange={(e) => setHpName(e.target.value)} tabIndex={-1} autoComplete="off" />
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="website_url" className="text-sm font-medium text-brand-text">Адрес вашего сайта *</label>
        <input
          id="website_url"
          type="url"
          placeholder="https://example.ru"
          value={websiteUrl}
          onChange={(e) => setWebsiteUrl(e.target.value)}
          required
          className="input-field"
        />
        <p className="text-xs text-brand-muted">
          Бренд, нишу и регион определим автоматически по сайту — вводить не нужно.
        </p>
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="email" className="text-sm font-medium text-brand-text">Email для отчёта *</label>
        <input
          id="email"
          type="email"
          placeholder="you@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          className="input-field"
        />
        <p className="text-xs text-brand-muted">Отчёт будет готов через 3–7 минут. Спам не рассылаем.</p>
      </div>

      {/* Задача 5.2 — конкуренты ссылками, по одной на строку */}
      <div className="flex flex-col gap-1.5 rounded-xl border border-accent-700/40 bg-accent-900/10 p-4">
        <label htmlFor="competitors" className="text-sm font-medium text-brand-textBright">
          Знаете конкурентов? Дайте ссылки на их сайты — отчёт будет точнее
        </label>
        <textarea
          id="competitors"
          rows={3}
          placeholder={'buspartner.by\nhttps://example2.by\n…по одной ссылке в строке, до 5'}
          value={competitors}
          onChange={(e) => setCompetitors(e.target.value)}
          className="input-field resize-y"
        />
        <p className="text-xs text-brand-muted">
          Необязательно. Особенно важно для регионального бизнеса. Если не знаете —
          подберём сами по поисковой выдаче вашей ниши и региона.
        </p>
      </div>

      {/* Два чекбокса согласия (Закон РБ № 99-З) */}
      <div className="card-surface p-4 flex flex-col gap-3 mt-2">
        <ConsentCheckbox id="consent_personal_data" checked={consentPersonal} onChange={setConsentPersonal}>
          Согласен с{' '}
          <a href="/privacy" target="_blank" rel="noopener noreferrer" className="text-accent-400 hover:underline">
            политикой обработки персональных данных
          </a>.
        </ConsentCheckbox>
        <ConsentCheckbox id="consent_cross_border" checked={consentCrossBorder} onChange={setConsentCrossBorder}>
          Согласен на трансграничную передачу данных в РФ и США (
          <a href="/privacy" target="_blank" rel="noopener noreferrer" className="text-accent-400 hover:underline">
            подробнее
          </a>).
        </ConsentCheckbox>
      </div>

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
          'Проверить мой сайт'
        )}
      </button>
    </form>
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
    <label htmlFor={id} className="flex items-start gap-3 cursor-pointer text-sm text-brand-text leading-relaxed">
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
