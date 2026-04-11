"""Import des CSV dans PostgreSQL pour MILPO."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Callable

import psycopg

DB_URL = "postgresql://hilpo:hilpo@localhost:5433/hilpo"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def iter_csv_rows(path: Path):
    with path.open(newline="", encoding="utf-8") as file:
        yield from csv.DictReader(file)


def normalize_post_row(row: dict[str, str]) -> dict[str, object]:
    return {
        **row,
        "shortcode": row["shortcode"] or None,
        "followed_post": row["followed_post"].lower() == "true",
        "suspected_bool": row["suspected"].lower() == "true",
        "authors_checked_bool": row["authors_checked"].lower() == "true",
        "boosted_post_bool": row["boosted_post"].lower() == "true",
    }


def normalize_media_row(row: dict[str, str]) -> dict[str, object]:
    return {
        **row,
        "width": int(row["width"]) if row["width"] else None,
        "height": int(row["height"]) if row["height"] else None,
        "duration": float(row["duration"]) if row["duration"] else None,
        "media_url": row["media_url"] or None,
        "thumbnail_url": row["thumbnail_url"] or None,
    }


def import_posts(cur, data_dir: Path = DATA_DIR, printer: Callable[[str], None] = print):
    """Import core_posts_rows.csv → posts."""
    rows = read_csv_rows(data_dir / "core_posts_rows.csv")
    printer(f"  {len(rows)} posts à importer...")
    for row in rows:
        cur.execute(
            """
            INSERT INTO posts (ig_media_id, shortcode, ig_user_id, caption, timestamp,
                               media_type, media_product_type, followed_post, suspected,
                               authors_checked, inserted_at, boosted_post)
            VALUES (%(ig_media_id)s, %(shortcode)s, %(ig_user_id)s, %(caption)s, %(timestamp)s,
                    %(media_type)s, %(media_product_type)s, %(followed_post)s, %(suspected_bool)s,
                    %(authors_checked_bool)s, %(inserted_at)s, %(boosted_post_bool)s)
            ON CONFLICT (ig_media_id) DO NOTHING
            """,
            normalize_post_row(row),
        )
    printer("  ✓ posts importés")


def import_lookups(cur, data_dir: Path = DATA_DIR, printer: Callable[[str], None] = print):
    """Peuple categories et visual_formats depuis les valeurs uniques du CSV."""
    categories = set()
    visual_formats = set()
    for row in iter_csv_rows(data_dir / "core_post_categories_rows.csv"):
        categories.add(row["category"])
        visual_formats.add(row["visual_format"])

    for name in sorted(categories):
        cur.execute(
            "INSERT INTO categories (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (name,),
        )
    printer(f"  ✓ {len(categories)} catégories")

    for name in sorted(visual_formats):
        cur.execute(
            "INSERT INTO visual_formats (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (name,),
        )
    printer(f"  ✓ {len(visual_formats)} formats visuels")


def import_heuristic_labels(cur, data_dir: Path = DATA_DIR, printer: Callable[[str], None] = print):
    """Import core_post_categories_rows.csv → heuristic_labels."""
    rows = read_csv_rows(data_dir / "core_post_categories_rows.csv")
    printer(f"  {len(rows)} labels heuristiques à importer...")
    for row in rows:
        cur.execute(
            """
            INSERT INTO heuristic_labels (ig_media_id, category_id, subcategory, strategy, visual_format_id)
            VALUES (
                %(ig_media_id)s,
                (SELECT id FROM categories WHERE name = %(category)s),
                %(subcategory)s,
                %(strategy)s,
                (SELECT id FROM visual_formats WHERE name = %(visual_format)s)
            )
            ON CONFLICT (ig_media_id) DO NOTHING
            """,
            row,
        )
    printer("  ✓ heuristic_labels importés")


def import_media(cur, data_dir: Path = DATA_DIR, printer: Callable[[str], None] = print):
    """Import core_post_media_rows.csv → post_media."""
    rows = read_csv_rows(data_dir / "core_post_media_rows.csv")
    printer(f"  {len(rows)} médias à importer...")
    for row in rows:
        cur.execute(
            """
            INSERT INTO post_media (ig_media_id, parent_ig_media_id, media_order, media_type,
                                    width, height, duration, media_url, thumbnail_url)
            VALUES (%(ig_media_id)s, %(parent_ig_media_id)s, %(media_order)s, %(media_type)s,
                    %(width)s, %(height)s, %(duration)s, %(media_url)s, %(thumbnail_url)s)
            ON CONFLICT (ig_media_id) DO NOTHING
            """,
            normalize_media_row(row),
        )
    printer("  ✓ post_media importés")


def select_sample(cur, n: int = 2000, seed: int = 42, test_ratio: float = 0.2, printer: Callable[[str], None] = print):
    """Sélectionne un échantillon stratifié de n posts avec splits et ordre."""
    cur.execute(
        """
        INSERT INTO sample_posts (ig_media_id, seed)
        SELECT ig_media_id, %(seed)s
        FROM (
            SELECT h.ig_media_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY h.visual_format_id, h.strategy
                       ORDER BY RANDOM()
                   ) AS rn,
                   COUNT(*) OVER (PARTITION BY h.visual_format_id, h.strategy) AS group_size
            FROM heuristic_labels h
            JOIN posts p ON p.ig_media_id = h.ig_media_id
            WHERE p.ig_user_id = 17841403755827826
        ) ranked
        WHERE rn <= GREATEST(1, ROUND(%(n)s::numeric * group_size / (
            SELECT COUNT(*) FROM heuristic_labels h2
            JOIN posts p2 ON p2.ig_media_id = h2.ig_media_id
            WHERE p2.ig_user_id = 17841403755827826
        )))
        ORDER BY RANDOM()
        LIMIT %(n)s
        ON CONFLICT (ig_media_id) DO NOTHING
        """,
        {"n": n, "seed": seed},
    )

    # Split et presentation_order sont immuables une fois assignés : les
    # réécrire contamine le test set (annotations attachées à ig_media_id,
    # donc elles bougent de split). Seuls les nouveaux posts (NULL) sont
    # assignés ici.
    cur.execute(
        """
        WITH ranked AS (
            SELECT sp.ig_media_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY h.visual_format_id, h.strategy
                       ORDER BY RANDOM()
                   ) AS rn,
                   CEIL(COUNT(*) OVER (PARTITION BY h.visual_format_id, h.strategy) * %(test_ratio)s) AS n_test_per_group
            FROM sample_posts sp
            JOIN heuristic_labels h ON h.ig_media_id = sp.ig_media_id
            WHERE sp.split IS NULL
        )
        UPDATE sample_posts SET split = CASE
            WHEN ig_media_id IN (SELECT ig_media_id FROM ranked WHERE rn <= n_test_per_group) THEN 'test'::split_type
            ELSE 'dev'::split_type
        END
        WHERE split IS NULL
        """,
        {"test_ratio": test_ratio},
    )

    cur.execute(
        """
        WITH start_order AS (
            SELECT COALESCE(MAX(presentation_order), 0) AS max_order
            FROM sample_posts
            WHERE presentation_order IS NOT NULL
        ),
        shuffled AS (
            SELECT ig_media_id,
                   ROW_NUMBER() OVER (ORDER BY RANDOM())
                   + (SELECT max_order FROM start_order) AS new_order
            FROM sample_posts
            WHERE presentation_order IS NULL
        )
        UPDATE sample_posts sp
        SET presentation_order = s.new_order
        FROM shuffled s
        WHERE sp.ig_media_id = s.ig_media_id
        """
    )

    cur.execute("SELECT split, COUNT(*) FROM sample_posts GROUP BY split ORDER BY split")
    splits = dict(cur.fetchall())
    printer(f"  ✓ {sum(splits.values())} posts échantillonnés (seed={seed})")
    printer(f"    dev: {splits.get('dev', 0)}, test: {splits.get('test', 0)}")
    printer("    ordre de présentation assigné")


def run_import(
    *,
    db_url: str = DB_URL,
    data_dir: Path = DATA_DIR,
    printer: Callable[[str], None] = print,
) -> None:
    printer("Connexion à PostgreSQL...")
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT setseed(0.42)")
            printer("\n1. Import des lookups...")
            import_lookups(cur, data_dir=data_dir, printer=printer)
            printer("\n2. Import des posts...")
            import_posts(cur, data_dir=data_dir, printer=printer)
            printer("\n3. Import des heuristic_labels...")
            import_heuristic_labels(cur, data_dir=data_dir, printer=printer)
            printer("\n4. Import des médias...")
            import_media(cur, data_dir=data_dir, printer=printer)
            printer("\n5. Sélection de l'échantillon...")
            select_sample(cur, printer=printer)
            conn.commit()
            printer("\n✓ Import terminé.")


def main():
    run_import()


__all__ = [
    "DATA_DIR",
    "DB_URL",
    "import_heuristic_labels",
    "import_lookups",
    "import_media",
    "import_posts",
    "iter_csv_rows",
    "main",
    "normalize_media_row",
    "normalize_post_row",
    "read_csv_rows",
    "run_import",
    "select_sample",
]
