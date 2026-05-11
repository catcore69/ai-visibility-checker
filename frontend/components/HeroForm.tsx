'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
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

  const [websiteUrl, setWebsiteUrl]   = useState('');
  const [brandName, setBrandName]     = useState('');
  const [niche, setNiche]             = useState('');
  const [email, setEmail]             = useState('');
  const [hpName, setHpName]           = useState(''); // honeypot
  const [loading, setLoading]         = useState(false);
  const [error, setError]             = useState('');
  const [turnstileToken, setTurnstileToken] = useState('');

  const turnstileRef   = useRef<HTMLDivElement>(null);
  const widgetIdRef    = useRef<string | null>(null);
  const mountedRef     = useRef(false);

  // Mount Turnstile once
//  useEffect(() => {
  //  if (mountedRef.current || !SITE_KEY) return;
    //mountedRef.current = true;

    //const tryRender = () => {
      //if (!turnstileRef.current || !window.turnstile) {
        //setTimeout(tryRender, 300);
        //return;
      //}
      //widgetIdRef.current = window.turnstile.render(turnstileRef.current, {
        //sitekey: SITE_KEY,
        //callback: (token: string) => setTurnstileToken(token),
        //'expired-callback': () => setTurnstileToken(''),
        //theme: 'light',
        //size: 'normal',
      //});
    //};
    //tryRender();

    //return () => {
      //if (widgetIdRef.current) {
        //window.turnstile?.remove(widgetIdRef.current);
      //}
    //};
  //}, []);

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    // Honeypot check (client-side early exit, server also checks)
    if (hpName) return;

    if (!websiteUrl || !brandName || !niche || !email) {
      setError('Пожалуйста, заполните все поля.');
      return;
    }
    //if (SITE_KEY && !turnstileToken) {
      //setError('Пожалуйста, подождите — загружается проверка защиты от ботов.');
      //return;
    //}

    setLoading(true);
    try {
      const fingerprintId = await getFingerprint();

      const payload: CheckPayload = {
        url:     websiteUrl.trim(),
        brand_name:      brandName.trim(),
        niche:           niche.trim(),
        email:           email.trim().toLowerCase(),
	turnstile_token: '',      
        fingerprint_id:  fingerprintId,
        hp_name:         hpName,
        utm_source:      searchParams.get('utm_source') || undefined,
        utm_medium:      searchParams.get('utm_medium') || undefined,
        utm_campaign:    searchParams.get('utm_campaign') || undefined,
      };

      const result = await submitCheck(payload);
      router.push(`/proverka/verify-email?id=${result.report_id}&email=${encodeURIComponent(email)}`);
    } catch (err: unknown) {
      // Reset turnstile
//      if (widgetIdRef.current) window.turnstile?.reset(widgetIdRef.current);
  //    setTurnstileToken('');

      const axiosErr = err as { response?: { data?: { detail?: string } }; message?: string };
      const detail = axiosErr.response?.data?.detail;
      if (typeof detail === 'string') {
        setError(detail);
      } else if (Array.isArray(detail)) {
        setError((detail as { msg: string }[]).map(d => d.msg).join(', '));
      } else {
        setError('Что-то пошло не так. Попробуйте ещё раз.');
      }
    } finally {
      setLoading(false);
    }
  }, [websiteUrl, brandName, niche, email, hpName, turnstileToken, router, searchParams]);

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-lg mx-auto flex flex-col gap-4" noValidate>
      {/* Honeypot – hidden from real users */}
      <div className="hp-field" aria-hidden="true">
        <input
          type="text"
          name="name"
          value={hpName}
          onChange={e => setHpName(e.target.value)}
          tabIndex={-1}
          autoComplete="off"
        />
      </div>

      {/* Website URL */}
      <div className="flex flex-col gap-1.5">
        <label htmlFor="website_url" className="text-sm font-medium text-gray-900">
          Сайт вашей компании
        </label>
        <input
          id="website_url"
          type="url"
          placeholder="https://example.com"
          value={websiteUrl}
          onChange={e => setWebsiteUrl(e.target.value)}
          required
          className="border border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100 bg-white"
        />
      </div>

      {/* Brand Name */}
      <div className="flex flex-col gap-1.5">
        <label htmlFor="brand_name" className="text-sm font-medium text-gray-900">
          Название бренда
        </label>
        <input
          id="brand_name"
          type="text"
          placeholder="Например: Сбербанк, Яндекс, Notion"
          value={brandName}
          onChange={e => setBrandName(e.target.value)}
          required
          className="border border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100 bg-white"
        />
      </div>

      {/* Niche */}
      <div className="flex flex-col gap-1.5">
        <label htmlFor="niche" className="text-sm font-medium text-gray-900">
          Ниша / тематика бизнеса
        </label>
        <input
          id="niche"
          type="text"
          placeholder="Например: онлайн-банкинг, доставка еды, SaaS для HR"
          value={niche}
          onChange={e => setNiche(e.target.value)}
          required
          className="border border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100 bg-white"
        />
      </div>

      {/* Email */}
      <div className="flex flex-col gap-1.5">
        <label htmlFor="email" className="text-sm font-medium text-gray-900">
          Email для получения отчёта
        </label>
        <input
          id="email"
          type="email"
          placeholder="you@company.com"
          value={email}
          onChange={e => setEmail(e.target.value)}
          required
          className="border border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100 bg-white"
        />
        <p className="text-xs text-gray-500">
          Отчёт будет готов через 3–7 минут. Спам не рассылаем.
        </p>
      </div>


      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-700">
          {error}
       </div>
      )}

      {/* Submit */}
      <button
        type="submit"
        disabled={loading}
        className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-bold text-base py-3.5 rounded-xl transition-colors flex items-center justify-center gap-2"
      >
        {loading ? (
          <>
            <span className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            Отправляем...
          </>
        ) : (
          '🔍 Проверить бесплатно'
        )}
      </button>

      <p className="text-center text-xs text-gray-400">
        Нажимая кнопку, вы соглашаетесь с обработкой персональных данных
      </p>
    </form>
  );
}
