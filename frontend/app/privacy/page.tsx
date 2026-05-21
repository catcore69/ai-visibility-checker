import { Logo } from '@/components/Logo';

export const metadata = {
  title: 'Политика обработки персональных данных — CatCore GEO Studio',
  description:
    'Политика обработки персональных данных оператора CatCore GEO Studio. Закон Республики Беларусь от 07.05.2021 № 99-З «О защите персональных данных».',
};

/**
 * Этап 1.4 ТЗ: на форме есть две обязательные ссылки на /privacy — ставим
 * корректную заглушку, чтобы ссылки не вели в 404.
 *
 * Полная политика по 13 разделам Закона РБ № 99-З — Этап 4 ТЗ. Этот файл
 * перепишется тогда. Сейчас задача: ссылки работают, юридическая структура
 * объявлена, фаундер видит TODO-список.
 */
export default function PrivacyPage() {
  return (
    <main className="min-h-screen bg-brand-bg text-brand-text">
      <header className="border-b border-brand-border/60">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <Logo height={26} />
          <span className="eyebrow hidden sm:inline">CatCore GEO Studio</span>
        </div>
      </header>

      <article className="max-w-3xl mx-auto px-6 py-16">
        <p className="eyebrow mb-3">Документ</p>
        <h1 className="font-heading text-3xl sm:text-4xl mb-4">
          Политика обработки персональных данных
        </h1>
        <p className="text-brand-muted text-sm mb-10">
          Закон Республики Беларусь от 07.05.2021 № 99-З
          «О защите персональных данных». Регулятор — Национальный центр защиты
          персональных данных Республики Беларусь (НЦЗПД, cpp.by).
        </p>

        <div className="card-surface p-5 mb-10 border-accent-700/40">
          <p className="text-sm text-brand-text leading-relaxed">
            <strong className="text-accent-300">Документ в стадии финализации.</strong>{' '}
            Полная политика проходит юридическую проверку и будет опубликована до
            запуска маркетинговых кампаний. Если вы хотите получить детали о том,
            какие данные мы собираем и кому передаём прямо сейчас — напишите на{' '}
            <a
              href="mailto:privacy@catcore.ru"
              className="text-accent-400 hover:underline"
            >
              privacy@catcore.ru
            </a>
            , ответим в течение 1 рабочего дня.
          </p>
        </div>

        <Section title="Кто оператор">
          <p>
            CatCore GEO Studio — оператор персональных данных в Республике Беларусь.
            Реквизиты оператора (ФИО самозанятой, УНП, адрес регистрации) —
            публикуются здесь после регистрации в НЦЗПД РБ.
          </p>
        </Section>

        <Section title="Какие данные собираем">
          <ul className="list-disc pl-5 flex flex-col gap-1">
            <li>Email — для отправки отчёта и follow-up писем.</li>
            <li>URL сайта клиента, название бренда, описание ниши.</li>
            <li>IP-адрес и браузерный fingerprint — для защиты от абуза.</li>
            <li>
              Метаданные согласий: дата, время, IP в момент проставления чекбоксов.
            </li>
          </ul>
        </Section>

        <Section title="Цели обработки">
          <ul className="list-disc pl-5 flex flex-col gap-1">
            <li>Предоставление бесплатной услуги AI Visibility-аудита.</li>
            <li>Отправка отчёта и связанных материалов на email.</li>
            <li>Связь с клиентом по результатам аудита.</li>
            <li>Внутренняя аналитика воронки (агрегированная).</li>
          </ul>
        </Section>

        <Section title="Кому передаём (трансграничная передача)">
          <p className="mb-3">
            Часть обработки выполняется сервисами за пределами Беларуси — это
            трансграничная передача, требующая отдельного согласия (вы проставили
            его при заполнении формы):
          </p>
          <ul className="list-disc pl-5 flex flex-col gap-1">
            <li>
              <strong className="text-brand-textBright">Российская Федерация:</strong>{' '}
              Timeweb (хостинг, S3), YandexGPT, GigaChat (Сбер), XMLRiver
              (поисковая выдача).
            </li>
            <li>
              <strong className="text-brand-textBright">США:</strong> OpenAI (GPT-4o-mini),
              Google (Gemini), DeepSeek, Perplexity.
            </li>
          </ul>
          <p className="mt-3 text-brand-muted text-sm">
            LLM-провайдерам мы передаём только обезличенные промпты по нише (например,
            «посоветуй базу отдыха в Приморье»), персональные данные клиентов туда
            не уходят.
          </p>
        </Section>

        <Section title="Сроки хранения">
          <ul className="list-disc pl-5 flex flex-col gap-1">
            <li>
              Активные данные — 1 год с момента последнего взаимодействия, затем
              обезличиваются или удаляются.
            </li>
            <li>Согласия — 3 года для подтверждения правомерности обработки.</li>
          </ul>
        </Section>

        <Section title="Ваши права">
          <ul className="list-disc pl-5 flex flex-col gap-1">
            <li>Отозвать согласие через email privacy@catcore.ru.</li>
            <li>Получить информацию об обработке своих данных.</li>
            <li>Запросить изменение, дополнение или удаление.</li>
            <li>Обжаловать действия оператора в НЦЗПД РБ (cpp.by).</li>
          </ul>
        </Section>

        <p className="text-xs text-brand-muted mt-12">
          Дата последнего обновления: документ в работе. Окончательная версия — после
          регистрации оператора в НЦЗПД и юридической проверки.
        </p>
      </article>
    </main>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="font-heading text-xl mb-3">{title}</h2>
      <div className="text-sm text-brand-text leading-relaxed">{children}</div>
    </section>
  );
}
