'use client';

import { useEffect, useState } from 'react';
import { STEP_LABELS, STEP_PROGRESS, LOADING_FACTS } from '@/lib/loading-facts';
import type { ReportStatus } from '@/lib/api';

interface Props {
  status: ReportStatus;
}

const FACT_INTERVAL = 8000; // ms

export default function ProgressTracker({ status }: Props) {
  const [factIndex, setFactIndex] = useState(0);
  const [facts] = useState(() => {
    const shuffled = [...LOADING_FACTS].sort(() => Math.random() - 0.5);
    return shuffled;
  });

  useEffect(() => {
    const interval = setInterval(() => {
      setFactIndex(i => (i + 1) % facts.length);
    }, FACT_INTERVAL);
    return () => clearInterval(interval);
  }, [facts]);

  const currentStep = status.current_step ?? status.status;
  const stepLabel   = STEP_LABELS[currentStep] ?? 'Обрабатываем...';
  const progress    = status.progress_pct ?? STEP_PROGRESS[currentStep] ?? 5;

  const steps = [
    { key: 'detecting_niche',     label: 'Определение ниши' },
    { key: 'finding_competitors', label: 'Поиск конкурентов' },
    { key: 'generating_prompts',  label: 'Генерация запросов' },
    { key: 'polling_models',      label: 'Опрос ИИ-ассистентов' },
    { key: 'analyzing',           label: 'Анализ упоминаний' },
    { key: 'building_report',     label: 'Формирование отчёта' },
  ];

  const stepKeys = steps.map(s => s.key);
  const currentStepIndex = stepKeys.indexOf(currentStep);

  return (
    <div className="w-full max-w-xl mx-auto flex flex-col gap-6">
      {/* Progress bar */}
      <div>
        <div className="flex justify-between text-sm mb-2">
          <span className="font-medium text-gray-900">{stepLabel}</span>
          <span className="font-bold text-blue-600">{progress}%</span>
        </div>
        <div className="w-full h-3 bg-gray-100 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-600 rounded-full transition-all duration-700 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>
        {status.estimated_wait_seconds && progress < 95 && (
          <p className="text-xs text-gray-400 mt-1.5 text-right">
            Ещё ~{Math.ceil(status.estimated_wait_seconds / 60)} мин.
          </p>
        )}
      </div>

      {/* Step list */}
      <div className="flex flex-col gap-2">
        {steps.map((step, idx) => {
          const isDone    = currentStepIndex > idx || status.status === 'done';
          const isActive  = currentStepIndex === idx && status.status !== 'done';
          const isPending = currentStepIndex < idx && status.status !== 'done';

          return (
            <div key={step.key} className="flex items-center gap-3">
              <div
                className={`w-7 h-7 rounded-full flex items-center justify-center text-sm flex-shrink-0 transition-colors ${
                  isDone
                    ? 'bg-green-500 text-white'
                    : isActive
                    ? 'bg-blue-600 text-white pulse-dot'
                    : 'bg-gray-100 text-gray-400'
                }`}
              >
                {isDone ? '✓' : idx + 1}
              </div>
              <span
                className={`text-sm ${
                  isDone    ? 'text-gray-500 line-through' :
                  isActive  ? 'text-gray-900 font-medium' :
                  isPending ? 'text-gray-400' : 'text-gray-400'
                }`}
              >
                {step.label}
              </span>
            </div>
          );
        })}
      </div>

      {/* Queue position */}
      {status.queue_position && status.queue_position > 1 && (
        <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 text-sm text-blue-700">
          Вы в очереди: позиция <strong>#{status.queue_position}</strong>.
          Как только дойдёт очередь — запустим анализ автоматически.
        </div>
      )}

      {/* Rotating facts */}
      <div className="bg-gray-50 border border-gray-100 rounded-2xl p-5 min-h-[80px] flex items-start gap-3">
        <span className="text-xl mt-0.5 flex-shrink-0">💡</span>
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">
            Знаете ли вы?
          </p>
          <p className="text-sm text-gray-700 leading-relaxed transition-all">
            {facts[factIndex % facts.length]}
          </p>
        </div>
      </div>
    </div>
  );
}
