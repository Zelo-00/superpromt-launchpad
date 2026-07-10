---
name: mermaid-diagrams
description: Рисование диаграмм кодом через Mermaid (https://github.com/mermaid-js/mermaid) — флоучарты, sequence, ER-диаграммы БД, диаграммы классов, состояний, Gantt, git-графы, mindmap, C4-архитектура. Текст → диаграмма, рендер в браузере/markdown/CLI. Применяй на слова «диаграмма», «схема», «флоучарт», «блок-схема», «архитектура», «последовательность», «ER», «gantt», «визуализировать процесс».
---

# Mermaid — диаграммы как код

Источник: https://github.com/mermaid-js/mermaid · песочница: https://mermaid.live.

## Когда применять
Схема процесса/алгоритма (flowchart), взаимодействие сервисов (sequenceDiagram), схема БД
(erDiagram), архитектура (C4/flowchart subgraph), план работ (gantt), состояния (stateDiagram),
структура идей (mindmap). НЕ применять: графики данных (→ chart-библиотеки), пиксельная точность (→ SVG вручную).

## Как применять
1. Выбери тип: flowchart TD/LR · sequenceDiagram · erDiagram · classDiagram · stateDiagram-v2 ·
   gantt · gitGraph · mindmap · C4Context.
2. Пиши текстом: `flowchart LR; A[Запрос] --> B{PSQ>=0.8?}; B -- да --> C[Исполнение]; B -- нет --> D[Ремонт] --> A`.
3. Рендер: в markdown (GitHub/GitLab — блок ```mermaid), в вебе —
   `import mermaid from 'mermaid'; mermaid.initialize({startOnLoad:true, theme:'dark'})`,
   в CLI — `mmdc -i in.mmd -o out.svg` (@mermaid-js/mermaid-cli).
4. Дисциплина: ≤ 20 узлов на диаграмму (иначе дели на subgraph/несколько), осмысленные подписи
   рёбер, направление по потоку чтения (TD для иерархий, LR для процессов), тёмная/светлая тема
   под фон страницы; диаграмма живёт рядом с кодом и обновляется в том же PR.
