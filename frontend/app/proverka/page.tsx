import { Suspense } from 'react';
import HeroForm from '@/components/HeroForm';
import { Logo } from '@/components/Logo';

export const metadata = {
  title: 'Проверить AI Visibility бренда — CatCore GEO Studio',
  description:
    'Бесплатная проверка: как часто ИИ-ассистенты упоминают ваш бренд. Получите PDF-отчёт с анализом ChatGPT, YandexGPT, GigaChat, Gemini и других.',
};

const MODELS = [
  'ChatGPT',
  'YandexGPT',
  'GigaChat',
  'Gemini',
  'Perplexity',
  'DeepSeek',
  'Яндекс-поиск с AI-блоком',
];

const BENEFITS = [
  { title: 'AI Visibility Score',         desc: 'Единая оценка 0–100 для сравнения с конкурентами' },
  { title: 'Сравнение с 5 конкурентами',  desc: 'Кто лидирует в ИИ-поиске вашей ниши и почему' },
  { title: 'Реальные ответы ИИ',          desc: 'Цитаты того, что говорят модели о вашем бренде' },
  { title: 'План на 3 уровня',            desc: 'Что сделать своими руками, что — структурно, что — с нами' },
  { title: 'PDF-отчёт',                   desc: 'Документ для руководства, маркетинга и клиентов' },
  { title: 'За 3–7 минут',                desc: 'Автоматический анализ — результат приходит на почту' },
];

export default function ProverkaPage() {
  return (
    <main className="min-h-screen bg-brand-bg text-brand-text">
      {/* ===== Шапка ===== */}
      <header className="border-b border-brand-border/60">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <Logo height={26} />
          <span className="eyebrow hidden sm:inline">CatCore GEO Studio</span>
        </div>
      </header>

      {/* ===== Hero ===== */}
      <section className="max-w-5xl mx-auto px-6 pt-20 pb-10 text-center">
        <div className="inline-flex items-center gap-2 border border-brand-border bg-brand-surface px-3 py-1.5 rounded-full mb-8">
          <span className="w-1.5 h-1.5 rounded-full bg-accent-500 pulse-dot" />
          <span className="eyebrow !text-brand-text">Бесплатная проверка · результат за 3–7 минут</span>
        </div>

        <h1 className="font-heading text-5xl sm:text-6xl leading-[0.95] tracking-tight mb-6">
          Как ИИ-ассистенты видят
          <br />
          <span className="text-accent-400">ваш бренд?</span>
        </h1>

        <p className="text-lg text-brand-muted max-w-2xl mx-auto mb-10 leading-relaxed">
          Проверьте AI Visibility своего бренда — насколько часто ChatGPT, YandexGPT, GigaChat и
          другие ИИ упоминают вас по сравнению с конкурентами. Получите PDF-отчёт с разбором и
          планом действий.
        </p>

        <div className="flex flex-wrap justify-center gap-2 mb-4">
          {MODELS.map((m) => (
            <span
              key={m}
              className="text-xs font-medium tracking-wide px-3 py-1.5 rounded-full border border-brand-border bg-brand-surface text-brand-text"
            >
              {m}
            </span>
          ))}
        </div>
      </section>

      {/* ===== Форма ===== */}
      <section className="max-w-3xl mx-auto px-6 pb-8">
        <div className="card-surface p-8 shadow-card">
          <h2 className="font-heading text-2xl text-center mb-1">Введите данные вашего бренда</h2>
          <p className="text-center text-sm text-brand-muted mb-6">
            Заполните 4 поля — за 3–7 минут получите отчёт на e-mail
          </p>
          <Suspense>
            <HeroForm />
          </Suspense>
        </div>
      </section>

      {/* ===== Второй CTA — для тех, у кого сайта ещё нет (Этап 5.1 ТЗ) ===== */}
      <section className="max-w-3xl mx-auto px-6 pb-20">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 rounded-2xl border border-brand-border bg-brand-surface/50 px-6 py-5">
          <div>
            <p className="font-heading text-base text-brand-textBright">
              Только планируете сайт?
            </p>
            <p className="text-sm text-brand-muted mt-0.5">
              Инструмент проверяет уже существующий сайт. Если сайта пока нет — расскажем,
              как сразу собрать его под выдачу ИИ.
            </p>
          </div>
          <a
            href="https://t.me/catcore_sitebot"
            target="_blank"
            rel="noopener noreferrer"
            className="btn-secondary whitespace-nowrap flex-shrink-0"
          >
            Записаться на консультацию
          </a>
        </div>
      </section>

      {/* ===== Что в отчёте ===== */}
      <section className="max-w-5xl mx-auto px-6 pb-24">
        <div className="text-center mb-10">
          <p className="eyebrow mb-3">Что в отчёте</p>
          <h2 className="font-heading text-3xl sm:text-4xl">8 страниц предметного разбора</h2>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {BENEFITS.map((b, i) => (
            <div
              key={b.title}
              className="card-surface p-6 hover:border-accent-700 transition-colors"
            >
              <div className="font-heading text-accent-400 text-sm mb-3">
                {String(i + 1).padStart(2, '0')}
              </div>
              <p className="font-heading text-lg mb-1.5">{b.title}</p>
              <p className="text-brand-muted text-sm leading-relaxed">{b.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ===== Подвал ===== */}
      <footer className="border-t border-brand-border/60">
        <div className="max-w-6xl mx-auto px-6 py-10 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <Logo height={22} />
          </div>
          <p className="text-xs text-brand-muted text-center sm:text-right">
            CatCore GEO Studio — бутиковая студия GEO-оптимизации под выдачу ИИ.
            <br className="hidden sm:block" />
            Инструмент бесплатный, спам не рассылаем.
          </p>
        </div>
      </footer>
    </main>
  );
}
