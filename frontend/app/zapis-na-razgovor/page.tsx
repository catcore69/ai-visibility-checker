'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { Logo } from '@/components/Logo';

// URL виджета онлайн-записи Bitrix24. Прописывается в .env фронта:
// NEXT_PUBLIC_BITRIX_BOOKING_URL=https://catcore.bitrix24.by/booking/?id=1
const BOOKING_URL = process.env.NEXT_PUBLIC_BITRIX_BOOKING_URL || '';

function BookingContent() {
  const params = useSearchParams();
  const reportId = params.get('report_id') || '';

  // Пробрасываем report_id в виджет, чтобы Bitrix связал запись с отчётом.
  const widgetSrc = BOOKING_URL
    ? `${BOOKING_URL}${BOOKING_URL.includes('?') ? '&' : '?'}UF_CRM_REPORT_ID=${encodeURIComponent(reportId)}`
    : '';

  return (
    <main className="min-h-screen bg-brand-bg text-brand-text">
      <header className="border-b border-brand-border/60">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <Logo height={26} />
          <span className="eyebrow hidden sm:inline">CatCore GEO Studio</span>
        </div>
      </header>

      <section className="max-w-3xl mx-auto px-6 pt-16 pb-10 text-center">
        <p className="eyebrow mb-3">Разговор с экспертом</p>
        <h1 className="font-heading text-3xl sm:text-4xl mb-4">
          Выберите удобное время
        </h1>
        <p className="text-brand-muted max-w-xl mx-auto leading-relaxed">
          30 минут по видеосвязи. Покажем ваш сайт глазами ИИ, объясним, какие 3–5 действий
          дадут максимальный эффект конкретно для вашего бизнеса, и честно скажем, какой пакет
          вам реально нужен. Без давления и попыток продать дороже.
        </p>
      </section>

      <section className="max-w-3xl mx-auto px-6 pb-20">
        {widgetSrc ? (
          <div className="card-surface overflow-hidden" style={{ minHeight: 600 }}>
            <iframe
              src={widgetSrc}
              title="Онлайн-запись на разговор"
              width="100%"
              height="640"
              style={{ border: 'none', display: 'block' }}
            />
          </div>
        ) : (
          <div className="card-surface p-8 text-center">
            <p className="text-brand-text mb-4">
              Виджет записи временно недоступен. Напишите нам напрямую — договоримся о времени:
            </p>
            <a
              href="https://t.me/catcore_sitebot"
              target="_blank"
              rel="noopener noreferrer"
              className="btn-primary inline-flex"
            >
              Написать в Telegram
            </a>
          </div>
        )}

        <p className="text-center text-xs text-brand-muted mt-6">
          После записи мы пришлём подтверждение на email и пригласим в видеовстречу
          за день до разговора.
        </p>
      </section>
    </main>
  );
}

export default function BookingPage() {
  return (
    <Suspense>
      <BookingContent />
    </Suspense>
  );
}
