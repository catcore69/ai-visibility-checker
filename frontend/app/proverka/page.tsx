import { Suspense } from 'react';
import HeroForm from '@/components/HeroForm';

export const metadata = {
  title: 'Проверить AI Visibility бренда — CatCore GEO',
  description: 'Бесплатная проверка: как часто ИИ-ассистенты упоминают ваш бренд. Получите PDF-отчёт с анализом ChatGPT, YandexGPT, GigaChat, Gemini и других.',
};

const MODELS = [
  { name: 'ChatGPT',    icon: '🤖', color: 'bg-gray-100 text-gray-700' },
  { name: 'YandexGPT',  icon: '🔶', color: 'bg-yellow-50 text-yellow-800' },
  { name: 'GigaChat',   icon: '💬', color: 'bg-green-50 text-green-800' },
  { name: 'Gemini',     icon: '♊', color: 'bg-blue-50 text-blue-800' },
  { name: 'Perplexity', icon: '🔍', color: 'bg-violet-50 text-violet-800' },
  { name: 'DeepSeek',   icon: '🌊', color: 'bg-purple-50 text-purple-800' },
  { name: 'Алиса',      icon: '🎙️', color: 'bg-pink-50 text-pink-800' },
];

const BENEFITS = [
  { icon: '📊', title: 'AI Visibility Score',       desc: 'Единая оценка 0–100 для сравнения с конкурентами'         },
  { icon: '🏆', title: 'Сравнение с 5 конкурентами', desc: 'Кто лидирует в ИИ-поиске вашей ниши'                     },
  { icon: '💬', title: 'Реальные ответы ИИ',         desc: 'Скриншоты того, что говорят модели о вашем бренде'       },
  { icon: '🎯', title: '5 рекомендаций',             desc: 'Конкретные шаги для роста AI Visibility за 90 дней'      },
  { icon: '📄', title: 'PDF-отчёт',                  desc: 'Профессиональный документ для руководства и клиентов'    },
  { icon: '⚡', title: 'За 3–7 минут',               desc: 'Автоматический анализ — результат на почту сразу'        },
];

export default function ProverkaPage() {
  return (
    <main className="min-h-screen bg-gradient-to-b from-blue-50 to-white">
      {/* Hero section */}
      <div className="max-w-5xl mx-auto px-4 pt-16 pb-8 text-center">
        {/* Badge */}
        <div className="inline-flex items-center gap-2 bg-blue-100 text-blue-700 text-sm font-semibold px-4 py-2 rounded-full mb-8">
          <span>✨</span>
          <span>Бесплатная проверка · Результат за 3–7 минут</span>
        </div>

        <h1 className="text-4xl sm:text-5xl font-black text-gray-900 mb-5 leading-tight">
          Как ИИ-ассистенты видят<br />
          <span className="text-blue-600">ваш бренд?</span>
        </h1>

        <p className="text-lg text-gray-600 max-w-2xl mx-auto mb-10 leading-relaxed">
          Проверьте AI Visibility своего бренда — насколько часто ChatGPT, YandexGPT, GigaChat
          и другие ИИ упоминают вас по сравнению с конкурентами.
          Получите PDF-отчёт с рекомендациями.
        </p>

        {/* Models */}
        <div className="flex flex-wrap justify-center gap-2 mb-12">
          {MODELS.map(model => (
            <span
              key={model.name}
              className={`flex items-center gap-1.5 text-sm font-medium px-3 py-1.5 rounded-full ${model.color}`}
            >
              <span>{model.icon}</span>
              {model.name}
            </span>
          ))}
        </div>
      </div>

      {/* Form */}
      <div className="max-w-5xl mx-auto px-4 pb-16">
        <div className="bg-white rounded-3xl shadow-xl shadow-blue-100/50 p-8 border border-blue-50">
          <h2 className="text-xl font-bold text-gray-900 text-center mb-6">
            Введите данные вашего бренда
          </h2>
          <Suspense>
            <HeroForm />
          </Suspense>
        </div>
      </div>

      {/* Benefits */}
      <div className="max-w-5xl mx-auto px-4 pb-16">
        <h2 className="text-2xl font-black text-center text-gray-900 mb-8">
          Что вы получите в отчёте
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {BENEFITS.map(b => (
            <div key={b.title} className="bg-white rounded-2xl p-5 border border-gray-100 flex gap-4">
              <span className="text-2xl mt-0.5">{b.icon}</span>
              <div>
                <p className="font-bold text-gray-900 text-sm mb-1">{b.title}</p>
                <p className="text-gray-500 text-sm leading-relaxed">{b.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Social proof */}
      <div className="max-w-5xl mx-auto px-4 pb-20 text-center">
        <p className="text-gray-400 text-sm">
          Инструмент от <strong className="text-gray-600">CatCore GEO Studio</strong> ·
          Специализируемся на GEO-продвижении для российского и международного рынка
        </p>
      </div>
    </main>
  );
}
