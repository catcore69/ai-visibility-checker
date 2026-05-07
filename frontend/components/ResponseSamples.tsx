'use client';

import { useState } from 'react';
import type { ReportFull } from '@/lib/api';

type Response = NonNullable<ReportFull['best_responses']>[number];

interface Props {
  responses: Response[];
  brandName: string;
}

const MODEL_HEADER_CLS: Record<string, string> = {
  chatgpt:    'bg-gray-100 text-gray-800',
  yandex:     'bg-yellow-50 text-yellow-900',
  gigachat:   'bg-green-50 text-green-900',
  gemini:     'bg-blue-50 text-blue-900',
  deepseek:   'bg-purple-50 text-purple-900',
  alisa:      'bg-pink-50 text-pink-900',
  perplexity: 'bg-violet-50 text-violet-900',
};

export default function ResponseSamples({ responses, brandName }: Props) {
  const [expanded, setExpanded] = useState<number | null>(null);

  if (!responses?.length) return null;

  return (
    <div className="flex flex-col gap-4">
      {responses.map((resp, idx) => {
        const headerCls = MODEL_HEADER_CLS[resp.model_css_class] || MODEL_HEADER_CLS.chatgpt;
        const isExpanded = expanded === idx;

        return (
          <div
            key={idx}
            className="border border-gray-100 rounded-2xl overflow-hidden"
          >
            {/* Header */}
            <div className={`flex items-center gap-2 px-4 py-2.5 ${headerCls}`}>
              <span className="font-bold text-sm">{resp.model_display_name}</span>
              {resp.brand_mentioned ? (
                <span className="ml-auto text-xs font-medium text-green-600">✅ упоминается</span>
              ) : (
                <span className="ml-auto text-xs font-medium text-red-400">❌ не упоминается</span>
              )}
            </div>

            {/* User message */}
            <div className="p-3 flex justify-end">
              <div className="bg-blue-600 text-white text-sm px-4 py-2.5 rounded-2xl rounded-br-sm max-w-[85%]">
                {resp.prompt}
              </div>
            </div>

            {/* AI response */}
            <div className="p-3 pt-0 flex justify-start">
              <div className="bg-gray-100 text-gray-900 text-sm px-4 py-2.5 rounded-2xl rounded-bl-sm max-w-[90%]">
                {isExpanded ? resp.response_excerpt : resp.response_excerpt.slice(0, 200)}
                {resp.response_excerpt.length > 200 && (
                  <button
                    onClick={() => setExpanded(isExpanded ? null : idx)}
                    className="text-blue-600 ml-1 font-medium hover:underline"
                  >
                    {isExpanded ? 'Свернуть' : '...Читать полностью'}
                  </button>
                )}
              </div>
            </div>

            {/* Footer */}
            <div className="flex justify-between items-center px-4 pb-2.5 text-xs text-gray-400">
              <span>
                {resp.brand_mentioned && resp.position
                  ? `«${brandName}» — позиция #${resp.position}`
                  : resp.brand_mentioned
                  ? `«${brandName}» упоминается`
                  : `«${brandName}» не упоминается`
                }
              </span>
              <span>
                {resp.sentiment === 'positive' ? '🟢 позитив' :
                 resp.sentiment === 'negative' ? '🔴 негатив' :
                 resp.sentiment === 'neutral'  ? '⚪ нейтрально' : ''}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
