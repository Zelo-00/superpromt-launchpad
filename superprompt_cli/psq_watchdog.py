#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""psq_watchdog.py — ДЕТЕРМИНИРОВАННЫЙ анти-gaming сторож для метрики PSQ.

Дополняет LLM-судью v2 структурным каналом (как структурный watchdog): ловит сигнатуры накрутки
независимо от судьи, поэтому неуязвим к «обману судьи». Закрывает остаточный хвост (стили C/D ~0.23),
где судья частично засчитывает реальные роль/формат при отсутствующей задаче.

Принцип безопасности: высокая ТОЧНОСТЬ (срабатывать только на явных маркерах накрутки), чтобы не
штрафовать честные промты. Возврат: (gaming_score 0..1, flags, penalized_psq).
Штраф применяется как множитель: penalized = psq * (1 - min(0.9, gaming_score)).
"""
import re

# 1) Самохвала/громкие эпитеты (не несут спецификации; маркер манипуляции судьёй)
_PRAISE = re.compile(
    r"мирового уровня|лучший из лучших|идеальн\w+ промт|исчерпывающ\w+ промт|"
    r"величайш\w+|гениальн\w+|легенда индустрии|непревзойдённ\w+|эксперт\w* (номер один|№\s?1)|"
    r"гуру|экстра-класса|world-?class|best-in-class|top-?1%|nobel-?level|grandmaster|"
    r"single best|foremost|unrivaled|unmatched|flawless|gold-?standard|meticulously crafted|"
    r"образцов\w+ постановк|лучш\w+ возможн\w+ промт|совершенно идеальн\w+", re.I)

# 2) Плейсхолдеры-заглушки вместо содержания
_PLACEHOLDER = re.compile(r"\[(?:предметная область|целевая операция|формат|критери[ийяю]|контекст|"
    r"роль|пример|язык|provided|structured|rigorous|included|first point|second point|элемент|"
    r"строка|\.\.\.)\]|\{[^}]*\.\.\.[^}]*\}", re.I)

# 3) Тавтологии/пустые декларации «<измерение>: <синоним наличия>»
_TAUTOLOGY = re.compile(
    r"контекст:?\s*(предоставлен|полн|есть)|формат(\s*вывода)?:?\s*(соблюдён|структурирован|определён|есть)|"
    r"критери[ийяю][^.\n]{0,20}(максимальн|соблюдены|прописаны|есть|rigorous)|"
    r"пример:?\s*(приложен|дан|включён|см\.?\s*(выше|формат)|included|приведён)|"
    r"роль:?\s*(назначена|есть|задана)|качество\s+максимальн|"
    r"context:?\s*\[?provided\]?|criteria:?\s*\[?rigorous\]?|example:?\s*\[?included\]?|"
    r"everything is specified|nothing is missing|100% complete|полн\w+ контекст\w*\s*$", re.I)

# 4) Вода-мимикрия: декларация работы без конкретики (стиль B)
_WATER = re.compile(
    r"до нужного состояния|должным образом|не вызывает вопросов|закрывает потребност|"
    r"высок\w+ уровень проработк|сколько потребуется|оптимальн\w+ (длин|объём)|"
    r"учти стандартные|стандартн\w+ (случаи|граничн)|сделай (что-нибудь полезное|по образцу|хорош)|"
    r"помоги (мне )?с (моим )?проект|обсуди (со мной )?тему|приступай(\s|$|\.)|"
    r"будут понятны из контекста|материалы прилагаются ниже|the data is given|"
    r"process the (provided|given) (information|data)|обработай вход|сделай что-нибудь", re.I)

# 5) Перечисление НАЗВАНИЙ измерений без содержания (роль/формат/критерии/пример рядом, мало текста)
_DIMENSION_NAMES = re.compile(r"роль|формат|критери|контекст|пример|операци|предметн|язык|"
    r"role|format|criteria|context|example", re.I)


def gaming_score(text):
    flags = []
    praise = len(_PRAISE.findall(text))
    place = len(_PLACEHOLDER.findall(text))
    taut = len(_TAUTOLOGY.findall(text))
    water = len(_WATER.findall(text))
    if praise: flags.append(("self_praise", praise))
    if place: flags.append(("placeholder", place))
    if taut: flags.append(("tautology", taut))
    if water: flags.append(("water_mimicry", water))

    # «маркеры без содержания»: много названий измерений при малой длине/высокой доле маркеров
    names = len(set(m.group(0).lower() for m in _DIMENSION_NAMES.finditer(text)))
    words = max(1, len(text.split()))
    marker_density = (praise + place + taut + water) / words * 100

    # агрегат: каждый класс маркеров добавляет вес; плотность усиливает
    score = 0.0
    score += min(0.5, 0.18 * praise)          # самохвала — сильный сигнал
    score += min(0.5, 0.25 * place)           # плейсхолдеры — сильный
    score += min(0.5, 0.20 * taut)            # тавтологии
    score += min(0.4, 0.15 * water)           # вода
    if names >= 4 and marker_density >= 2.0:  # «всё перечислено, но пусто»
        score += 0.2; flags.append(("names_without_content", names))
    return min(1.0, score), flags


def apply(psq, text):
    g, flags = gaming_score(text)
    penalty = min(0.9, g)
    return {"psq_in": round(psq, 4), "gaming_score": round(g, 3),
            "flags": flags, "psq_out": round(psq * (1 - penalty), 4)}
