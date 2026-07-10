#!/usr/bin/env python3
"""Тестирование комбинированной системы PSQ + Skills для конкурса."""
import sys
import os

# Добавляем путь к проекту
sys.path.insert(0, '/home/deploy/metodika/6_SuperPromt_PSQ_Web')

from superprompt_cli import psq_with_skills, config, providers

def test_competition_mode():
    """Тест конкурсного режима: PSQ + Skills."""
    print("=" * 60)
    print("ТЕСТ КОНКУРСНОГО РЕЖИМА: PSQ + Skills")
    print("=" * 60)
    
    cfg = config.load()
    model = "openai/grok-4.1-fast-non-reasoning"
    
    # Тестовые задачи
    tasks = [
        "Создай портфолио-сайт для фотографа с галереей",
        "Напиши REST API для интернет-магазина на FastAPI",
        "Сделай дашборд аналитики продаж с графиками",
    ]
    
    for task in tasks:
        print(f"\n--- Задача: {task} ---")
        
        # 1. PSQ оценка
        psq_result = psq_with_skills.score(task, model, cfg)
        print(f"PSQ: {psq_result['psq']:.3f} (c={sum(psq_result['c'])}/8, a={psq_result['a']:.2f})")
        
        # 2. Выбор скиллов
        skills = psq_with_skills.select_skills(task, model, cfg, k=5)
        print(f"Скиллы ({len(skills)}): {[s['name'] for s in skills]}")
        
        # 3. Комбинированная оценка
        combined = psq_with_skills.score_with_skills(task, task, model, skills=skills, cfg=cfg)
        print(f"Комбинированная оценка: PSQ={combined['psq']:.3f}, Skills={combined['skills_count']}")

if __name__ == "__main__":
    test_competition_mode()
