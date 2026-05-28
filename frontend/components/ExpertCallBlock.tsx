'use client';

import { useState } from 'react';
import { addContact, type ContactPayload } from '@/lib/api';

interface Props {
  reportId: string;
  /** Колбэк после успешной отправки или отказа — чтобы родитель скрыл блок. */
  onResolved?: (resolved: 'submitted' | 'dismissed') => void;
}

const TIMES = [
  { value: 'утро', label: 'Утро' },
  { value: 'день', label: 'День' },
  { value: 'вечер', label: 'Вечер' },
  { value: 'любое', label: 'Любое' },
];

/**
 * Блок «🔥 Хочу комментарий эксперта» (Этап 5.2.2 ТЗ).
 *
 * Показывается на странице ожидания после ~70% прогресса. Собирает горячий
 * лид: имя + телефон/Telegram + удобное время + 2 согласия. Отправляет
 * через POST /report/{id}/contact — это немедленно шлёт эксперту Telegram
 * «Горячий лид» и гасит email-цепочку.
 */
export default function ExpertCallBlock({ reportId, onResolved }: Props) {
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
      setError('Оставьте телефон или Telegram.');
      return;
    }
    if (!consentPersonal || !consentCrossBorder) {
      setError('Нужны оба согласия.');
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
      onResolved?.('submitted');
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } };
      setError(axiosErr.response?.data?.detail || 'Не удалось отправить. Попробуйте ещё раз.');
    } finally {
      setLoading(false);
    }
  };

  if (done) {
    return (
      <div className="card-surface p-6 border-success/40">
        <p className="font-heading text-lg mb-1 text-success">Спасибо!</p>
        <p className="text-sm text-brand-text">
          Эксперт свяжется с вами в течение 1 рабочего дня. Удобное время —{' '}
          <strong className="text-accent-300">{preferred}</strong>.
        </p>
      </div>
    );
  }

  return (
    <div className="card-surface p-6 border-accent-700/40">
      <div className="flex items-start justify-between gap-4 mb-1">
        <p className="font-heading text-lg">Хотите услышать комментарий эксперта?</p>
        <button
          type="button"
          onClick={() => onResolved?.('dismissed')}
          className="text-xs text-brand-muted hover:text-brand-text whitespace-nowrap mt-1"
        >
          Не сейчас →
        </button>
      </div>
      <p className="text-sm text-brand-muted mb-4 leading-relaxed">
        Оставьте телефон или Telegram — позвоним в течение 1 рабочего дня, расскажем
        главное по результатам и ответим на вопросы. Без давления, без попыток продать
        прямо в звонке.
      </p>

      <form onSubmit={handleSubmit} className="flex flex-col gap-3" noValidate>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Ваше имя"
          className="input-field"
          required
        />
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <input
            type="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="Телефон +7 / +375"
            className="input-field"
          />
          <input
            type="text"
            value={telegram}
            onChange={(e) => setTelegram(e.target.value)}
            placeholder="@telegram"
            className="input-field"
          />
        </div>

        <div className="flex flex-wrap gap-2">
          {TIMES.map((t) => (
            <button
              key={t.value}
              type="button"
              onClick={() => setPreferred(t.value)}
              className={[
                'px-3 py-1.5 rounded-lg border text-sm transition-colors',
                preferred === t.value
                  ? 'border-accent-500 bg-accent-700/20 text-brand-textBright'
                  : 'border-brand-border text-brand-text hover:border-accent-700',
              ].join(' ')}
            >
              {t.label}
            </button>
          ))}
        </div>

        <label className="flex items-start gap-2.5 cursor-pointer text-xs text-brand-text leading-relaxed mt-1">
          <input
            type="checkbox"
            checked={consentPersonal}
            onChange={(e) => setConsentPersonal(e.target.checked)}
            className="mt-0.5 w-4 h-4 accent-accent-500 flex-shrink-0"
          />
          <span>
            Согласен с{' '}
            <a href="/privacy" target="_blank" rel="noopener noreferrer" className="text-accent-400 hover:underline">
              политикой обработки персональных данных
            </a>
            .
          </span>
        </label>
        <label className="flex items-start gap-2.5 cursor-pointer text-xs text-brand-text leading-relaxed">
          <input
            type="checkbox"
            checked={consentCrossBorder}
            onChange={(e) => setConsentCrossBorder(e.target.checked)}
            className="mt-0.5 w-4 h-4 accent-accent-500 flex-shrink-0"
          />
          <span>Согласен на трансграничную передачу данных в РФ и США.</span>
        </label>

        {error && (
          <div className="border border-accent-700/60 bg-accent-900/30 rounded-xl px-3 py-2 text-sm text-accent-200">
            {error}
          </div>
        )}

        <button type="submit" disabled={!canSubmit} className="btn-primary w-full mt-1">
          {loading ? 'Отправляем…' : 'Хочу комментарий эксперта'}
        </button>
      </form>
    </div>
  );
}
