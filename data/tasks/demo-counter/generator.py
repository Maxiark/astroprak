import random

def generate(seed: int | None = None) -> dict:
    rng = random.Random(seed)
    
    # Генерируем модельный массив наблюдений
    n_points = rng.randint(20, 35)
    counts = [rng.randint(5, 50) for _ in range(n_points)]
    mean_val = round(sum(counts) / len(counts), 2)

    return {
        "id": "demo-counter",
        "title": "Демонстрационный тренажёр: Анализ импульсов",
        "max_score": 10.0,
        "entry_point": "widget.html",
        "data": {
            "counts": counts,
            "expected_mean": mean_val
        },
        "schema": {
            "fields": [
                {
                  "id": "model_type",
                  "kind": "choice",
                  "label": "Тип распределения",
                  "options": ["Пуассоновское", "Гауссово", "Равномерное", "Степенное"]
                },
                {
                  "id": "mean_count",
                  "kind": "number",
                  "label": "Среднее число импульсов",
                  "unit": "имп/с"
                }
            ]
        }
    }
