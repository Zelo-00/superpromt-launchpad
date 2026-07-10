---
name: lottie-animation
description: Создание и встраивание анимаций Lottie (https://github.com/diffusionstudio/lottie) — векторные JSON-анимации для веба и приложений: иконки, лоадеры, микроинтеракции, анимированные иллюстрации, логотипы. Рендер через lottie-web/dotLottie, программная сборка сцен. Применяй на слова «анимация», «lottie», «микроинтеракция», «лоадер», «анимированная иконка/логотип», «motion».
---

# Lottie — векторная анимация для веба и приложений

Источник: https://github.com/diffusionstudio/lottie (типизированная работа с Lottie-форматом) ·
рендереры: lottie-web, @lottiefiles/dotlottie-web.

## Когда применять
Микроинтеракции (лайк, чекбокс, переключатель), лоадеры/скелетоны, анимированные иконки и
логотипы, onboarding-иллюстрации, пустые состояния. НЕ применять: сложное видео (→ mp4/WebM),
физика игры (→ движок), простое появление (→ CSS transition достаточно).

## Как применять
1. Источник анимации: готовый .json/.lottie (LottieFiles) или программная сборка
   (diffusionstudio/lottie — типизированные слои/шейпы/кейфреймы из кода).
2. Веб: `import { DotLottie } from '@lottiefiles/dotlottie-web'` → канвас; или lottie-web →
   `lottie.loadAnimation({container, path:'anim.json', loop, autoplay})`.
3. Управление: play/pause/seek по событиям (hover, scroll, submit); сегменты для состояний
   (start→loop→success).
4. Дисциплина: файл ≤ 200KB (оптимизировать слои), `prefers-reduced-motion` → статичный кадр,
   lazy-загрузка вне первого экрана, fallback-иконка при ошибке загрузки.
