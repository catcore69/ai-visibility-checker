'use client';

import { useState, useRef, useCallback } from 'react';
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

const SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY || '';

export default function HeroForm() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [websiteUrl, setWebsiteUrl] = useState('');
  const [brandName, setBrandName]   = useState('');
  const [niche, setNiche]           = useState('');
  const [email, setEmail]           = useState('');
  const [hpName, setHpName]         = useState(''); // honeypot
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState('');
  const [turnstileToken] = useState('');

  // Turnstile сейчас отключён (см. бэкенд) — компонент сохраняем для будущего включения.
  const widgetIdRef = useRef<string | null>(null);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setError('');

      if (hpName) return; // honeypot tripped

      if (!websiteUrl || !brandName || !niche || !email) {
        setError('Пожалуйста, заполните все поля.');
        return;
      }

      setLoading(true);
      try {
        const fingerprintId = await getFingerprint();

        const payload: CheckPayload = {
          url: websiteUrl.trim(),
          brand_name: brandName.trim(),
          niche: niche.trim(),
          email: email.trim().toLowerCase(),
          turnstile_token: '',
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
        if (widgetIdRef.current) window.turnstile?.reset(widgetIdRef.current);
        const axiosErr = err as { response?: { data?: { detail?: string } }; message?: string };
        const detail = axiosErr.response?.data?.detail;
        if (typeof detail === 'string') {
          setError(detail);
        } else if (Array.isArray(detail)) {
          setError((detail as { msg: string }[]).map((d) => d.msg).join(', '));
        } else {
          setError('Что-то пошло не так. Попробуйте ещё раз.');
        }
      } finally {
        setLoading(false);
      }
    },
    [websiteUrl, brandName, niche, email, hpName, turnstileToken, router, searchParams],
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
        label="Сайт вашей компании"
        type="url"
        placeholder="https://example.com"
        value={websiteUrl}
        onChange={setWebsiteUrl}
        required
      />

      <Field
        id="brand_name"
        label="Название бренда"
        type="text"
        placeholder="Например: Сбербанк, Яндекс, Notion"
        value={brandName}
        onChange={setBrandName}
        required
      />

      <Field
        id="niche"
        label="Ниша / тематика бизнеса"
        type="text"
        placeholder="Например: онлайн-банкинг, доставка еды, SaaS для HR"
        value={niche}
        onChange={setNiche}
        required
      />

      <Field
        id="email"
        label="Email для получения отчёта"
        type="email"
        placeholder="you@company.com"
        value={email}
        onChange={setEmail}
        required
        helper="Отчёт будет готов через 3–7 минут. Спам не рассылаем."
      />

      {error && (
        <div className="border border-accent-700/60 bg-accent-900/30 rounded-xl px-4 py-3 text-sm text-accent-200">
          {error}
        </div>
      )}

      <button type="submit" disabled={loading} className="btn-primary mt-2 w-full">
        {loading ? (
          <span className="inline-flex items-center justify-center gap-2">
            <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            Отправляем…
          </span>
        ) : (
          'Проверить бесплатно'
        )}
      </button>

      <p className="text-center text-xs text-brand-muted">
        Нажимая кнопку, вы соглашаетесь с обработкой персональных данных
      </p>
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
