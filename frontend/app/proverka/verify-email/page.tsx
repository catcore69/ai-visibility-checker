'use client';

import { useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { resendEmail } from '@/lib/api';
import { Suspense } from 'react';

function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const email     = searchParams.get('email')     || '';
  const reportId  = searchParams.get('id')        || '';

  const [resendState, setResendState] = useState<'idle' | 'loading' | 'sent' | 'error'>('idle');
  const [cooldown, setCooldown]       = useState(0);

  const handleResend = async () => {
    if (!reportId || resendState === 'loading' || cooldown > 0) return;

    setResendState('loading');
    try {
      await resendEmail(reportId);
      setResendState('sent');
      // 60-second cooldown
      setCooldown(60);
      const timer = setInterval(() => {
        setCooldown(prev => {
          if (prev <= 1) { clearInterval(timer); return 0; }
          return prev - 1;
        });
      }, 1000);
    } catch {
      setResendState('error');
      setTimeout(() => setResendState('idle'), 4000);
    }
  };

  const maskedEmail = email
    ? email.replace(/^(.{1,2})(.*)(@.*)$/, (_, a, b, c) => a + '*'.repeat(Math.max(1, b.length)) + c)
    : '';

  return (
    <div className="min-h-screen bg-gradient-to-b from-blue-50 to-white flex items-center justify-center px-4">
      <div className="max-w-md w-full text-center">
        {/* Icon */}
        <div className="w-24 h-24 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-8 text-4xl">
          📧
        </div>

        <h1 className="text-3xl font-black text-gray-900 mb-4">
          Подтвердите email
        </h1>

        <p className="text-gray-600 mb-3 leading-relaxed">
          Мы отправили письмо на{' '}
          <strong className="text-gray-900">{maskedEmail || 'вашу почту'}</strong>.
        </p>

        <p className="text-gray-500 text-sm mb-8 leading-relaxed">
          Нажмите на кнопку в письме — после этого автоматически запустится
          анализ вашего бренда в ИИ-ассистентах. Обычно письмо приходит в течение 1–2 минут.
          Проверьте папку «Спам», если письмо не пришло.
        </p>

        {/* Steps */}
        <div className="bg-white rounded-2xl border border-gray-100 p-5 mb-8 text-left">
          <p className="text-sm font-semibold text-gray-500 mb-4 uppercase tracking-wide">
            Что произойдёт дальше:
          </p>
          <div className="flex flex-col gap-3">
            {[
              { num: '1', text: 'Откройте письмо от Cat Core GEO' },
              { num: '2', text: 'Нажмите «Подтвердить и получить отчёт»' },
              { num: '3', text: 'Дождитесь анализа (3–7 минут)' },
              { num: '4', text: 'Получите PDF-отчёт на почту' },
            ].map(step => (
              <div key={step.num} className="flex items-center gap-3">
                <div className="w-7 h-7 rounded-full bg-blue-600 text-white text-sm font-bold flex items-center justify-center flex-shrink-0">
                  {step.num}
                </div>
                <p className="text-sm text-gray-700">{step.text}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Resend */}
        <div className="flex flex-col items-center gap-2">
          <p className="text-sm text-gray-500">Письмо не пришло?</p>
          <button
            onClick={handleResend}
            disabled={resendState === 'loading' || cooldown > 0}
            className="text-sm font-semibold text-blue-600 hover:text-blue-700 disabled:text-gray-400 disabled:cursor-not-allowed transition-colors"
          >
            {resendState === 'loading' ? (
              'Отправляем...'
            ) : resendState === 'sent' ? (
              `✓ Отправлено${cooldown > 0 ? ` · повторно через ${cooldown}с` : ''}`
            ) : resendState === 'error' ? (
              'Ошибка. Попробуйте ещё раз'
            ) : cooldown > 0 ? (
              `Повторная отправка через ${cooldown}с`
            ) : (
              'Отправить повторно'
            )}
          </button>
        </div>

        {/* Footer */}
        <p className="text-xs text-gray-400 mt-10">
          Письмо отправлено с адреса no-reply@catcore.ru ·{' '}
          <a href="/proverka" className="text-blue-600 hover:underline">
            Начать заново
          </a>
        </p>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <VerifyEmailContent />
    </Suspense>
  );
}
