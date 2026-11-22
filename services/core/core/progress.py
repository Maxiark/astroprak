"""Read-only catalogue progress from saved submissions, never from task generators."""
from decimal import Decimal


def catalogue_task_ids(manifests):
    # Match the catalogue's open action, including legacy manifests without kind.
    return {m["id"] for m in manifests
            if not m.get("hidden", False) and m.get("kind") not in ("theory", "material")}


def get_progress(conn, user_id, manifests):
    task_ids = catalogue_task_ids(manifests)
    rows = conn.execute(
        """
        SELECT task_id, MAX(score) FILTER (
            WHERE score > '-Infinity'::float8 AND score < 'Infinity'::float8
        ) AS best_score
        FROM attempts
        WHERE user_id = %s AND submitted_at IS NOT NULL AND task_id = ANY(%s)
        GROUP BY task_id
        """,
        (user_id, sorted(task_ids)),
    ).fetchall()
    tasks = {
        row["task_id"]: {
            "status": "solved" if row["best_score"] is not None else "submitted_ungraded",
            "best_score": row["best_score"],
        }
        for row in rows
    }
    scores = [t["best_score"] for t in tasks.values() if t["best_score"] is not None]
    return {
        "user_id": user_id,
        "summary": {
            "solved_tasks": len(scores),
            "available_tasks": len(task_ids),
            "total_score": float(sum((Decimal(str(s)) for s in scores), Decimal(0))),
        },
        "tasks": tasks,
    }
