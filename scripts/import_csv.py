#!/usr/bin/env python3
"""Import des CSV dans PostgreSQL pour HILPO."""

import csv
import sys
from pathlib import Path

import psycopg

DB_URL = "postgresql://hilpo:hilpo@localhost:5433/hilpo"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def import_posts(cur):
    """Import core_posts_rows.csv → posts."""
    path = DATA_DIR / "core_posts_rows.csv"
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"  {len(rows)} posts à importer...")
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
            {
                **row,
                "shortcode": row["shortcode"] or None,
                "followed_post": row["followed_post"].lower() == "true",
                "suspected_bool": row["suspected"].lower() == "true",
                "authors_checked_bool": row["authors_checked"].lower() == "true",
                "boosted_post_bool": row["boosted_post"].lower() == "true",
            },
        )
    print(f"  ✓ posts importés")


def import_lookups(cur):
    """Peuple categories et visual_formats depuis les valeurs uniques du CSV."""
    path = DATA_DIR / "core_post_categories_rows.csv"
    categories = set()
    visual_formats = set()

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            categories.add(row["category"])
            visual_formats.add(row["visual_format"])

    for name in sorted(categories):
        cur.execute(
            "INSERT INTO categories (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (name,),
        )
    print(f"  ✓ {len(categories)} catégories")

    for name in sorted(visual_formats):
        cur.execute(
            "INSERT INTO visual_formats (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (name,),
        )
    print(f"  ✓ {len(visual_formats)} formats visuels")


def import_heuristic_labels(cur):
    """Import core_post_categories_rows.csv → heuristic_labels."""
    path = DATA_DIR / "core_post_categories_rows.csv"
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"  {len(rows)} labels heuristiques à importer...")
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
    print(f"  ✓ heuristic_labels importés")


def import_media(cur):
    """Import core_post_media_rows.csv → post_media."""
    path = DATA_DIR / "core_post_media_rows.csv"
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"  {len(rows)} médias à importer...")
    for row in rows:
        cur.execute(
            """
            INSERT INTO post_media (ig_media_id, parent_ig_media_id, media_order, media_type,
                                    width, height, duration, media_url, thumbnail_url)
            VALUES (%(ig_media_id)s, %(parent_ig_media_id)s, %(media_order)s, %(media_type)s,
                    %(width)s, %(height)s, %(duration)s, %(media_url)s, %(thumbnail_url)s)
            ON CONFLICT (ig_media_id) DO NOTHING
            """,
            {
                **row,
                "width": int(row["width"]) if row["width"] else None,
                "height": int(row["height"]) if row["height"] else None,
                "duration": float(row["duration"]) if row["duration"] else None,
                "media_url": row["media_url"] or None,
                "thumbnail_url": row["thumbnail_url"] or None,
            },
        )
    print(f"  ✓ post_media importés")


def select_sample(cur, n=2000, seed=42):
    """Sélectionne un échantillon stratifié de n posts."""
    # Stratification sur visual_format × strategy (parmi les posts catégorisés)
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
        ) ranked
        WHERE rn <= GREATEST(1, ROUND(%(n)s::numeric * group_size / (
            SELECT COUNT(*) FROM heuristic_labels
        )))
        ORDER BY RANDOM()
        LIMIT %(n)s
        ON CONFLICT (ig_media_id) DO NOTHING
        """,
        {"n": n, "seed": seed},
    )
    cur.execute("SELECT COUNT(*) FROM sample_posts")
    count = cur.fetchone()[0]
    print(f"  ✓ {count} posts échantillonnés (stratifié, seed={seed})")


def main():
    print("Connexion à PostgreSQL...")
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            # Fixer le seed pour la reproductibilité
            cur.execute("SELECT setseed(0.42)")

            print("\n1. Import des lookups...")
            import_lookups(cur)

            print("\n2. Import des posts...")
            import_posts(cur)

            print("\n3. Import des heuristic_labels...")
            import_heuristic_labels(cur)

            print("\n4. Import des médias...")
            import_media(cur)

            print("\n5. Sélection de l'échantillon...")
            select_sample(cur)

            conn.commit()
            print("\n✓ Import terminé.")


if __name__ == "__main__":
    main()
