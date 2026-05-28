'use client';

import { trackCta } from '@/lib/api';

interface Props {
  reportId: string;
  brandName: string;
  score: number;
}

const TG_BOT_URL = process.env.NEXT_PUBLIC_TG_BOT_URL || 'https://t.me/catcore_sitebot';

export default function FinalCTA({ reportId, brandName, score }: Props) {
  const handleClick = async (action: string) => {
    try {
      await trackCta(reportId, action);
    } catch {
      // tracking — некритично
    }
  };

  const potentialScore = Math.min(score + 25, 100);
  // Главный CTA воронки — запись на разговор (наша форма заявки).
  const bookingUrl = `/zapis-na-razgovor?report_id=${reportId}&utm_source=ai_report&utm_campaign=cta_call_report_page`;

  return (
    <div className="rounded-3xl bg-brand-surface border border-accent-700/40 p-8 text-center flex flex-col items-center gap-5 relative overflow-hidden">
      <div
        aria-hidden
        className="absolute -right-12 -top-12 w-48 h-48 rounded-full"
        style={{
          background: 'radial-gradient(circle, rgba(166,61,61,0.35) 0%, rgba(166,61,61,0) 70%)',
        }}
      />

      <div className="relative">
        <p className="eyebrow mb-3">CatCore GEO Studio</p>
        <h2 className="font-heading text-2xl sm:text-3xl mb-3 leading-tight">
          Поднять «{brandName}» с {score} до {potentialScore}+ за 90 дней
        </h2>
        <p className="text-brand-muted text-base max-w-xl mx-auto">
          30 минут по видеосвязи. Покажем ваш сайт глазами ИИ, объясним, какие 3–5 действий
          дадут максимальный эффект, и честно скажем, какой пакет вам нужен. Без давления.
        </p>
      </div>

      <div className="flex flex-col sm:flex-row gap-3 w-full max-w-md relative">
        <a
          href={bookingUrl}
          onClick={() => handleClick('call')}
          className="btn-primary flex-1 inline-flex items-center justify-center"
        >
          Выбрать время разговора
        </a>
        <a
          href={TG_BOT_URL}
          target="_blank"
          rel="noopener noreferrer"
          onClick={() => handleClick('telegram_click')}
          className="btn-secondary flex-1 inline-flex items-center justify-center"
        >
          Написать в Telegram
        </a>
      </div>

      <p className="text-brand-muted text-xs relative">
        Бесплатно · Без обязательств · Отвечаем в рабочее время
      </p>
    </div>
  );
}
