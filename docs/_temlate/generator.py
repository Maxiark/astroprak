import random

def generate(seed: int | None = None) -> dict:
    """
    Генератор модельных данных и схемы бланка ответов.
    Детерминирован параметром seed.
    """
    rng = random.Random(seed)
    
    # 1. Физические параметры и расчетные величины
    param_true = round(rng.uniform(10.0, 50.0), 2)
    noise = [round(rng.gauss(0, 1.5), 2) for _ in range(20)]
    
    # 2. Формирование публичного пакета
    return {
        "id": "task-template",
        "title": "Название нового тренажёра",
        "max_score": 10.0,
        "entry_point": "widget.html",
        "data": {
            "param_true": param_true,
            "measurements": noise
        },
        "schema": {
            "fields": [
                {
                    "id": "profile_type",
                    "kind": "choice",
                    "label": "Модельный профиль",
                    "options": ["Вариант A", "Вариант B", "Вариант C"]
                },
                {
                    "id": "param_val",
                    "kind": "number",
                    "label": "Оцененный параметр",
                    "unit": "усл. ед."
                }
            ]
        }
    }
