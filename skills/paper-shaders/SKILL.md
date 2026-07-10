---
name: paper-shaders
description: Библиотека шейдер-материалов Paper Design (https://shaders.paper.design/) — источник готовых анимированных WebGL-фонов и эффектов для фронтенда и вёрстки. Mesh-градиенты, зерно/dithering, волны, дым, металлик, god rays. Применяй, когда нужен красивый живой фон, hero-секция, градиент, шейдер, визуальный эффект на сайте/лендинге. Пакеты @paper-design/shaders-react и @paper-design/shaders (vanilla JS).
---

# Paper Shaders — анимированные шейдер-материалы для веба

Источник: https://shaders.paper.design/ (галерея с живым превью и генератором кода) ·
код: https://github.com/paper-design/shaders · npm: `@paper-design/shaders-react`, `@paper-design/shaders`.

## Когда применять
Hero-фон лендинга, анимированный градиент, «дорогая» текстура (металл, дым, волны, зерно),
фон секции/карточки, эффект наведения. НЕ применять: когда нужна статичная простота,
слабые устройства без WebGL (давать CSS-фолбэк).

## Как применять
1. Выбери материал в галерее shaders.paper.design → подстрой параметры (цвета, скорость,
   масштаб) → скопируй сгенерированный код компонента.
2. React: `import { MeshGradient } from '@paper-design/shaders-react'` →
   `<MeshGradient colors={["#04121f","#134e7a","#2f8fd0"]} speed={0.25} style={{position:'absolute',inset:0}} />`.
3. Vanilla: пакет `@paper-design/shaders` — канвас-инстанс с теми же параметрами.
4. Дисциплина: шейдер — ФОН, поверх — контент с достаточным контрастом (проверь доступность);
   `prefers-reduced-motion` → статичный кадр/CSS-градиент; один шейдер на вьюпорт (производительность).

## Типовые материалы
MeshGradient (живой градиент) · Dithering (ретро-зерно) · Waves · Smoke/Fog · Metallic ·
GodRays · GrainGradient · Voronoi · DotOrbit. Все параметризуются цветами бренда.
