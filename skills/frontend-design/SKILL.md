---
name: frontend-design
description: Фронтенд-дизайн и вёрстка: HTML/CSS, responsive, UI/UX, цвета, типографика, компоновка, анимации, доступность. Для создания визуально красивых веб-сайтов и интерфейсов.
user-invocable: true
---

## Когда использовать
Создаёшь веб-сайт, лендинг, дашборд или любой UI где важен визуал и пользовательский опыт.

## Ключевые практики

### Структура HTML
- Семантические теги: `<header>`, `<nav>`, `<main>`, `<section>`, `<article>`, `<footer>`
- Мета-теги: viewport, charset, description, Open Graph
- Чистая иерархия: H1 → H2 → H3 (не пропускать уровни)
- ARIA-атрибуты для доступности

### CSS
- CSS-переменные для цветов, шрифтов, отступов
- Mobile-first подход: `@media (min-width: ...)` 
- Flexbox для одномерных раскладок, Grid для двумерных
- clamp() для адаптивных размеров: `font-size: clamp(1rem, 2vw, 1.5rem)`
- transitions/animations для интерактивности
- backdrop-filter для glass-morphism эффектов

### Дизайн-система
- Цветовая палитра: основной, акцентный, фоновый, текстовый (3-5 цветов)
- Типографика: максимум 2 шрифта, иерархия размеров
- Отступы: 4px/8px сетка (4, 8, 12, 16, 24, 32, 48, 64)
- Скругления:一致ные значения (8px, 12px, 16px)
- Тени: `box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1)`

### Responsive
- Breakpoints: 480px (mobile), 768px (tablet), 1024px (desktop), 1280px (wide)
- Контейнер: `max-width: 1200px; margin: 0 auto; padding: 0 1rem`
- Сетка: `grid-template-columns: repeat(auto-fit, minmax(300px, 1fr))`
- Изображения: `max-width: 100%; height: auto`

### Интерактивность
- Hover-эффекты: `transition: all 0.2s ease`
- Фокус-состояния: `outline: 2px solid accent; outline-offset: 2px`
- Спиннеры/лоадеры для асинхронных операций
- Плавные скроллы: `scroll-behavior: smooth`

### Производительность
- Lazy loading для изображений: `loading="lazy"`
- CSS contain для изоляции: `contain: layout style paint`
- will-change для анимаций: `will-change: transform`
- Минимум reflow/repaint

## Анти-паттерны
- Использование `!important`, inline-стили повсюду
- Отсутствие viewport meta тега
- Фиксированные размеры без media queries
- Текст в изображениях
- Недостаточный контраст текста (менее 4.5:1)

## Чеклист
[ ] семантический HTML [ ] CSS-переменные [ ] responsive [ ] mobile-first [ ] a11y (контраст, фокус) [ ] hover/transition [ ] lazy loading [ ] 2 шрифта макс [ ] 4px сетка
