'use client';

import { Suspense, useState } from 'react';
import { useSearchParams } from 'next/navigation';

import { addContact, type ContactPayload } from '@/lib/api';
import { Logo } from '@/components/Logo';

const TIMES = [
  { value: 'утро', label: 'Утро' },
  { value: 'день', label: 'День' },
  { value: 'вечер', label: 'Вечер' },
  { value: 'любое', label: 'Любое' },
];

function BookingForm() {
  const params = useSearchParams();
  const reportId = params.get('report_id') || '';

  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [telegram, setTelegram] = useState('');
  const [preferred, setPreferred] = useState('любое');
  const [consentPersonal, setConsentPersonal] = useState(false);
  const [consentCrossBorder, setConsentCrossBorder] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  const canSubmit =
    !!reportId &&
    name.trim().length >= 2 &&
    (phone.trim() || telegram.trim()) &&
    consentPersonal &&
    consentCrossBorder &&
    !loading;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (name.trim().length < 2) {
      setError('Укажите имя.');
      return;
    }
    if (!phone.trim() && !telegram.trim()) {
      setError('Оставьте телефон или Telegram — хотя бы одно.');
      return;
    }
    if (!consentPersonal || !consentCrossBorder) {
      setError('Нужны оба согласия (требование Закона РБ № 99-З).');
      return;
    }

    setLoading(true);
    try {
      const payload: ContactPayload = {
        name: name.trim(),
        phone: phone.trim() || undefined,
        telegram: telegram.trim() || undefined,
        preferred_time: preferred,
        consent_personal_data: consentPersonal,
        consent_cross_border: consentCrossBorder,
      };
      await addContact(reportId, payload);
      setDone(true);
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } };
      setError(axiosErr.response?.data?.detail || 'Не удалось отправить заявку. Попробуйте ещё раз.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-brand-bg text-brand-text">
      <header className="border-b border-brand-border/60">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <Logo height={26} />
          <span className="eyebrow hidden sm:inline">CatCore GEO Studio</span>
        </div>
      </header>

      <section className="max-w-2xl mx-auto px-6 pt-16 pb-10 text-center">
        <p className="eyebrow mb-3">Разговор с экспертом</p>
        <h1 className="font-heading text-3xl sm:text-4xl mb-4">
          Оставьте контакт — перезвоним
        </h1>
        <p className="text-brand-muted max-w-xl mx-auto leading-relaxed">
          30 минут по видеосвязи. Покажем ваш сайт глазами ИИ, объясним, какие 3–5 действий
          дадут максимальный эффект, и честно скажем, какой пакет вам реально нужен.
          Без давления и попыток продать дороже.
        </p>
      </section>

      <section className="max-w-2xl mx-auto px-6 pb-20">
        {done ? (
          <div className="card-surface p-8 text-center">
            <div className="text-success font-heading text-4xl mb-3">✓</div>
            <h2 className="font-heading text-2xl mb-3">Спасибо!</h2>
            <p className="text-brand-text">
              Эксперт свяжется с вами в течение 1 рабочего дня.
              Удобное время — <strong className="text-accent-300">{preferred}</strong>.
            </p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="card-surface p-8 flex flex-col gap-4" noValidate>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="name" className="text-sm font-medium text-brand-text">Ваше имя *</label>
              <input id="name" type="text" value={name} onChange={(e) => setName(e.target.value)}
                placeholder="Как к вам обращаться" required className="input-field" />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="flex flex-col gap-1.5">
                <label htmlFor="phone" className="text-sm font-medium text-brand-text">Телефон</label>
                <input id="phone" type="tel" value={phone} onChange={(e) => setPhone(e.target.value)}
                  placeholder="+7 999 123-45-67" className="input-field" />
              </div>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="telegram" className="text-sm font-medium text-brand-text">Telegram</label>
                <input id="telegram" type="text" value={telegram} onChange={(e) => setTelegram(e.target.value)}
                  placeholder="@username" className="input-field" />
              </div>
            </div>
            <p className="text-xs text-brand-muted -mt-2">Достаточно заполнить что-то одно — телефон или Telegram.</p>

            <div className="flex flex-col gap-2">
              <span className="text-sm font-medium text-brand-text">Удобное время для звонка</span>
              <div className="flex flex-wrap gap-2">
                {TIMES.map((t) => (
                  <button key={t.value} type="button" onClick={() => setPreferred(t.value)}
                    className={[
                      'px-4 py-2 rounded-xl border text-sm transition-colors',
                      preferred === t.value
                        ? 'border-accent-500 bg-accent-700/20 text-brand-textBright'
                        : 'border-brand-border text-brand-text hover:border-accent-700',
                    ].join(' ')}>
                    {t.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="card-surface p-4 flex flex-col gap-3 mt-2 !bg-brand-elevated/40">
              <label htmlFor="c1" className="flex items-start gap-3 cursor-pointer text-sm text-brand-text leading-relaxed">
                <input id="c1" type="checkbox" checked={consentPersonal} onChange={(e) => setConsentPersonal(e.target.checked)}
                  className="mt-0.5 w-4 h-4 accent-accent-500 flex-shrink-0" required />
                <span>Согласен с <a href="/privacy" target="_blank" rel="noopener noreferrer" className="text-accent-400 hover:underline">политикой обработки персональных данных</a>.</span>
              </label>
              <label htmlFor="c2" className="flex items-start gap-3 cursor-pointer text-sm text-brand-text leading-relaxed">
                <input id="c2" type="checkbox" checked={consentCrossBorder} onChange={(e) => setConsentCrossBorder(e.target.checked)}
                  className="mt-0.5 w-4 h-4 accent-accent-500 flex-shrink-0" required />
                <span>Согласен на трансграничную передачу данных в РФ и США (<a href="/privacy" target="_blank" rel="noopener noreferrer" className="text-accent-400 hover:underline">подробнее</a>).</span>
              </label>
            </div>

            {error && (
              <div className="border border-accent-700/60 bg-accent-900/30 rounded-xl px-4 py-3 text-sm text-accent-200">
                {error}
              </div>
            )}

            <button type="submit" disabled={!canSubmit} className="btn-primary w-full mt-2">
              {loading ? 'Отправляем…' : 'Хочу разговор с экспертом'}
            </button>
            <p className="text-center text-xs text-brand-muted">
              Без давления, без попыток продать прямо в звонке.
            </p>
          </form>
        )}
      </section>
    </main>
  );
}

export default function BookingPage() {
  return (
    <Suspense>
      <BookingForm />
    </Suspense>
  );
}
