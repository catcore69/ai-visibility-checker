import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'CatCore — AI Visibility Checker',
  description:
    'Бесплатный инструмент CatCore GEO Studio: проверьте, как ИИ-ассистенты (YandexGPT, GigaChat, Яндекс-поиск с AI-блоком, Google AI Overview, ChatGPT, Gemini, DeepSeek) видят ваш бренд по сравнению с конкурентами.',
  icons: { icon: '/favicon.ico' },
  openGraph: {
    title: 'CatCore — AI Visibility Checker',
    description: 'Проверьте, как ИИ-ассистенты видят ваш бренд',
    type: 'website',
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <head>
        {/* Cloudflare Turnstile */}
        <script
          src="https://challenges.cloudflare.com/turnstile/v0/api.js"
          async
          defer
        />
      </head>
      <body className="bg-brand-bg text-brand-text antialiased">{children}</body>
    </html>
  );
}
