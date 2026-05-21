import Image from 'next/image';

type LogoProps = {
  /** Высота лого в px. Ширина считается по соотношению ~4:1. */
  height?: number;
  className?: string;
  /** Если true — рендерит ссылку на главную */
  asLink?: boolean;
};

/**
 * Лого CatCore — вариант "Steel" (белое на тёмном фоне).
 * Используется в шапке всех страниц.
 */
export function Logo({ height = 28, className = '', asLink = true }: LogoProps) {
  const img = (
    <Image
      src="/brand/logo-steel.png"
      alt="CatCore — Digital Engineering"
      height={height}
      width={Math.round(height * 4)}
      priority
      style={{ height, width: 'auto' }}
    />
  );
  if (asLink) {
    return (
      <a href="/" aria-label="CatCore — на главную" className={`inline-flex items-center ${className}`}>
        {img}
      </a>
    );
  }
  return <span className={`inline-flex items-center ${className}`}>{img}</span>;
}
