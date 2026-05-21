'use client';

import { useState } from 'react';
import type { ReportFull } from '@/lib/api';

type Response = NonNullable<ReportFull['best_responses']>[number];

interface Props {
  responses: Response[];
  brandName: string;
}

export default function ResponseSamples({ responses, brandName }: Props) {
  const [expanded, setExpanded] = useState<number | null>(null);

  if (!responses?.length) return null;

  return (
    <div className="flex flex-col gap-4">
      {responses.map((resp, idx) => {
        const isExpanded = expanded === idx;
        return (
          <div key={idx} className="card-surface overflow-hidden">
            {/* Header */}
            <div className="flex items-center gap-2 px-4 py-2.5 bg-brand-elevated border-b border-brand-border">
              <span className="font-heading text-sm text-brand-textBright">
                {resp.model_display_name}
              </span>
              {resp.brand_mentioned ? (
                <span className="ml-auto text-xs font-medium text-success">упоминается</span>
              ) : (
                <span className="ml-auto text-xs font-medium text-danger">не упоминается</span>
              )}
            </div>

            {/* User message */}
            <div className="p-3 flex justify-end">
              <div className="bg-accent-500 text-white text-sm px-4 py-2.5 rounded-2xl rounded-br-sm max-w-[85%]">
                {resp.prompt}
              </div>
            </div>

            {/* AI response */}
            <div className="p-3 pt-0 flex justify-start">
              <div className="bg-brand-elevated text-brand-text text-sm px-4 py-2.5 rounded-2xl rounded-bl-sm max-w-[90%]">
                {isExpanded ? resp.response_excerpt : resp.response_excerpt.slice(0, 200)}
                {resp.response_excerpt.length > 200 && (
                  <button
                    onClick={() => setExpanded(isExpanded ? null : idx)}
                    className="text-accent-400 ml-1 font-medium hover:underline"
                  >
                    {isExpanded ? 'Свернуть' : '…Читать полностью'}
                  </button>
                )}
              </div>
            </div>

            <div className="flex justify-between items-center px-4 pb-2.5 text-xs text-brand-muted">
              <span>
                {resp.brand_mentioned && resp.position
                  ? `«${brandName}» — позиция #${resp.position}`
                  : resp.brand_mentioned
                    ? `«${brandName}» упоминается`
                    : `«${brandName}» не упоминается`}
              </span>
              <span>
                {resp.sentiment === 'positive'
                  ? 'позитив'
                  : resp.sentiment === 'negative'
                    ? 'негатив'
                    : resp.sentiment === 'neutral'
                      ? 'нейтрально'
                      : ''}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
