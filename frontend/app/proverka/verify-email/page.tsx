'use client';

import { Suspense, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { resendEmail } from '@/lib/api';
import { Logo } from '@/components/Logo';

function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const email = searchParams.get('email') || '';
  const reportId = searchParams.get('id') || '';

  const [resendState, setResendState] = useState<'idle' | 'loading' | 'sent' | 'error'>('idle');
  const [cooldown, setCooldown] = useState(0);

  const handleResend = async () => {
    if (!reportId || resendState === 'loading' || cooldown > 0) return;

    setResendState('loading');
    try {
      await resendEmail(reportId);
      setResendState('sent');
      setCooldown(60);
      const timer = setInterval(() => {
        setCooldown((prev) => {
          if (prev <= 1) {
            clearInterval(timer);
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
    } catch {
      setResendState('error');
      setTimeout(() => setResendState('idle'), 4000);
    }
  };

  const maskedEmail = email
    ? email.replace(
        /^(.{1,2})(.*)(@.*)$/,
        (_, a, b, c) => a + '*'.repeat(Math.max(1, b.length)) + c,
      )
    : '';

  return (
    <main className="min-h-screen bg-brand-bg flex flex-col">
      <header className="border-b border-brand-border/60">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <Logo height={26} />
          <span className="eyebrow hidden sm:inline">CatCore GEO Studio</span>
        </div>
      </header>

      <section className="flex-1 flex items-center justify-center px-6 py-16">
        <div className="max-w-md w-full text-center">
          <div className="w-20 h-20 rounded-full border border-brand-border bg-brand-surface flex items-center justify-center mx-auto mb-8">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-accent-400">
              <rect x="3" y="5" width="18" height="14" rx="2" />
              <path d="m3 7 9 6 9-6" />
            </svg>
          </div>

          <h1 className="font-heading text-3xl sm:text-4xl mb-4">Подтвердите email</h1>

          <p className="text-brand-text mb-3 leading-relaxed">
            Мы отправили письмо на <strong className="text-brand-textBright">{maskedEmail || 'вашу почту'}</strong>.
          </p>

          <p className="text-brand-muted text-sm mb-8 leading-relaxed">
            Нажмите кнопку в письме — после этого автоматически запустится анализ вашего бренда в
            ИИ-ассистентах. Обычно письмо приходит в течение 1–2 минут. Проверьте папку «Спам», если
            письмо не пришло.
          </p>

          <div className="card-surface p-5 mb-8 text-left">
            <p className="eyebrow mb-4">Что произойдёт дальше</p>
            <div className="flex flex-col gap-3">
              {[
                'Откройте письмо от CatCore GEO',
                'Нажмите «Подтвердить и получить отчёт»',
                'Дождитесь анализа (3–7 минут)',
                'Получите PDF-отчёт на почту',
              ].map((text, i) => (
                <div key={i} className="flex items-center gap-3">
                  <div className="w-7 h-7 rounded-full border border-accent-500 text-accent-300 font-heading text-sm flex items-center justify-center flex-shrink-0">
                    {i + 1}
                  </div>
                  <p className="text-sm text-brand-text">{text}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="flex flex-col items-center gap-2">
            <p className="text-sm text-brand-muted">Письмо не пришло?</p>
            <button
              onClick={handleResend}
              disabled={resendState === 'loading' || cooldown > 0}
              className="text-sm font-medium text-accent-400 hover:text-accent-300 disabled:text-brand-muted disabled:cursor-not-allowed transition-colors"
            >
              {resendState === 'loading'
                ? 'Отправляем…'
                : resendState === 'sent'
                  ? `✓ Отправлено${cooldown > 0 ? ` · повторно через ${cooldown}с` : ''}`
                  : resendState === 'error'
                    ? 'Ошибка. Попробуйте ещё раз'
                    : cooldown > 0
                      ? `Повторная отправка через ${cooldown}с`
                      : 'Отправить повторно'}
            </button>
          </div>

          <p className="text-xs text-brand-muted mt-10">
            Письмо отправлено с адреса no-reply@catcore.ru ·{' '}
            <a href="/proverka" className="text-accent-400 hover:underline">
              Начать заново
            </a>
          </p>
        </div>
      </section>
    </main>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <VerifyEmailContent />
    </Suspense>
  );
}
