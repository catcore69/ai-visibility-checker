'use client';

import { trackCta } from '@/lib/api';

interface Props {
  reportId: string;
  brandName: string;
  score: number;
}

const TG_BOT_URL   = process.env.NEXT_PUBLIC_TG_BOT_URL   || 'https://t.me/catcore_geo_bot';
const STUDIO_EMAIL = process.env.NEXT_PUBLIC_STUDIO_EMAIL  || 'hello@catcore.ru';

export default function FinalCTA({ reportId, brandName, score }: Props) {
  const handleClick = async (action: string) => {
    try {
      await trackCta(reportId, action);
    } catch {
      // Silent — tracking is non-critical
    }
  };

  const potentialScore = Math.min(score + 25, 100);

  return (
    <div className="rounded-3xl bg-gradient-to-br from-blue-700 to-blue-900 text-white p-8 text-center flex flex-col items-center gap-5">
      <div>
        <h2 className="text-2xl font-black mb-2">
          Хотите поднять «{brandName}» с {score} до {potentialScore}+ за 90 дней?
        </h2>
        <p className="text-blue-100 text-base max-w-lg mx-auto">
          Мы специализируемся на GEO-продвижении — системном присутствии бренда в ответах ИИ-ассистентов.
          Первые результаты видны через 30–45 дней.
        </p>
      </div>

      <div className="flex flex-col sm:flex-row gap-3 w-full max-w-sm">
        <a
          href={TG_BOT_URL}
          target="_blank"
          rel="noopener noreferrer"
          onClick={() => handleClick('telegram_click')}
          className="flex-1 bg-white text-blue-700 font-bold py-3.5 px-6 rounded-2xl hover:bg-blue-50 transition-colors text-center text-sm"
        >
          💬 Написать в Telegram
        </a>
        <a
          href={`mailto:${STUDIO_EMAIL}?subject=GEO-аудит для ${encodeURIComponent(brandName)}&body=Привет! Получил отчёт AI Visibility (score: ${score}) и хочу обсудить продвижение.`}
          onClick={() => handleClick('email_click')}
          className="flex-1 border border-white/30 text-white font-bold py-3.5 px-6 rounded-2xl hover:bg-white/10 transition-colors text-center text-sm"
        >
          📬 Написать на почту
        </a>
      </div>

      <p className="text-blue-200 text-xs">
        Бесплатный 30-минутный аудит · Без обязательств · Отвечаем в рабочее время
      </p>
    </div>
  );
}
