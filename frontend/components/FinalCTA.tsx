'use client';

import { trackCta } from '@/lib/api';

interface Props {
  reportId: string;
  brandName: string;
  score: number;
}

const TG_BOT_URL = process.env.NEXT_PUBLIC_TG_BOT_URL || 'https://t.me/catcore_geo_bot';
const STUDIO_EMAIL = process.env.NEXT_PUBLIC_STUDIO_EMAIL || 'hello@catcore.ru';

export default function FinalCTA({ reportId, brandName, score }: Props) {
  const handleClick = async (action: string) => {
    try {
      await trackCta(reportId, action);
    } catch {
      // tracking — некритично
    }
  };

  const potentialScore = Math.min(score + 25, 100);

  return (
    <div className="rounded-3xl bg-brand-surface border border-accent-700/40 p-8 text-center flex flex-col items-center gap-5 relative overflow-hidden">
      {/* Декоративный «коготь» в углу — единственный красный акцент крупным мазком */}
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
          Мы — бутиковая студия GEO-оптимизации. Системно строим присутствие бренда в ответах
          ИИ-ассистентов. Первые результаты — через 30–45 дней.
        </p>
      </div>

      <div className="flex flex-col sm:flex-row gap-3 w-full max-w-md relative">
        <a
          href={TG_BOT_URL}
          target="_blank"
          rel="noopener noreferrer"
          onClick={() => handleClick('telegram_click')}
          className="btn-primary flex-1 inline-flex items-center justify-center"
        >
          Написать в Telegram
        </a>
        <a
          href={`mailto:${STUDIO_EMAIL}?subject=GEO-аудит для ${encodeURIComponent(brandName)}&body=Привет! Получил отчёт AI Visibility (score: ${score}) и хочу обсудить продвижение.`}
          onClick={() => handleClick('email_click')}
          className="btn-secondary flex-1 inline-flex items-center justify-center"
        >
          Написать на почту
        </a>
      </div>

      <p className="text-brand-muted text-xs relative">
        Бесплатный 30-минутный аудит · Без обязательств · Отвечаем в рабочее время
      </p>
    </div>
  );
}
