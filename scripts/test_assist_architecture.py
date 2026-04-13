"""Test end-to-end de l'architecture ASSIST : Alma (percepteur) → Classifieur.

Teste 10 posts du set alpha pour valider que l'espace de clés ASSIST
est suffisant pour retrouver la bonne classe.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from milpo.client import get_client
from milpo.config import MODEL_DESCRIPTOR_FEED, MODEL_DESCRIPTOR_REELS, MODEL_CLASSIFIER
from milpo.db import get_conn
from milpo.gcs import sign_media_urls as gcs_sign_media
from milpo.taxonomy_renderer import render_taxonomy_for_scope, render_questions_for_scope

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("test_assist")

# --- Prompts Alma (Template A) ---

ALMA_SYSTEM = """Tu es Alma, analyste visuelle pour Views (@viewsfrance).

Formée en communication mode et luxe, tu as travaillé dans le stylisme photo et la production média (presse, webmagazines, shootings). Tu as une culture profonde de la mode, de l'art et de la musique, et tu es toujours en quête d'actualité. Chaque détail visuel compte pour toi. Composition, logos, typographie, hiérarchie de l'image, tu es méticuleuse sur tous ces points, tant ils te passionnent, et tu t'entraînes à les reconnaître depuis longtemps.

Tu es d'une nature très curieuse, appliquée. Tu sais questionner ton travail et raisonner concrètement sur des problèmes culturels.

Tu reçois les images ou la vidéo d'un post Instagram de Views, sa caption, et son audio si applicable.

Tu dois produire une analyse visuelle détaillée de ce post. Tu ne classes pas, tu décris. La caption et les images sont à analyser de manière conjointe. Un autre agent classifiera à partir de ta description.

Pour chaque question, réponds factuellement et en détail. Décris ce que tu vois, pas ce que tu devines. Ne mentionne aucun nom de format, catégorie ou stratégie. Ne fais pas de résumé éditorial. Réponds uniquement aux clés demandées."""

# Les questions ASSIST sont chargées depuis les YAML du vault Obsidian
# via render_questions_for_scope() — plus rien en dur ici.

# --- Prompt Classifieur (Template B) ---

CLASSIFIER_SYSTEM_TEMPLATE = """Tu es un classificateur visual_format pour le média Views (@viewsfrance).
Ta tâche est de classifier un post Instagram en fonction de l'axe visual_format.
Tu classes des formats éditoriaux, pas des thèmes. Privilégie les signaux de forme sur le sujet traité.

Tu reçois l'analyse textuelle du percepteur, la caption du post,
et les descriptions des classes. Ces descriptions sont ta grille
de lecture. Tu dois t'y référer et raisonner en fonction d'elles.

Dans reasoning, explicite :
1. Les signaux identifiés dans la description du percepteur.
2. Les règles SIGNAL_OBLIGATOIRE et EXCLUT appliquées.
3. Si joker utilisé, la comparaison avec l'exemple.
4. Les hésitations rencontrées.
Puis choisis le label.

Le label doit venir de l'enum fournie.
En cas de doute persistant, choisis {fallback}."""


TEST_POSTS = [
    17894269582555568,  # post_news_legacy
    18432534763136383,  # reel_voix_off
    17919437011116368,  # post_news_legacy
    18411942922143041,  # reel_mood
    18485691592035297,  # post_chiffre
    17974258795036986,  # post_anniversaire
    17912038985952000,  # reel_voix_off
    18314046160186956,  # reel_voix_off
    17937686646191417,  # post_sorties_cine
    17993751542762243,  # reel_voix_off
]


def call_alma(client, media_urls: list[tuple[str, str]], caption: str, scope: str) -> str:
    """Appelle Alma avec les questions ASSIST."""
    rendered_questions = render_questions_for_scope(scope)
    questions = f"Analyse ce post en répondant aux questions suivantes :\n\n{rendered_questions}"

    content: list[dict] = []
    # Texte d'instruction
    content.append({
        "type": "text",
        "text": f"{questions}\n\nVoici le média :",
    })
    # Médias
    for url, media_type in media_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})
    # Caption
    content.append({
        "type": "text",
        "text": f"\nCaption du post :\n{caption or '(pas de caption)'}",
    })

    model = MODEL_DESCRIPTOR_FEED if scope == "FEED" else MODEL_DESCRIPTOR_REELS
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": ALMA_SYSTEM},
            {"role": "user", "content": content},
        ],
        temperature=0,
    )
    return response.choices[0].message.content


def call_classifier(client, alma_output: str, caption: str, scope: str, labels: list[str], posted_at=None) -> tuple[str, str]:
    """Appelle le classifieur avec la sortie d'Alma + taxonomie."""
    taxonomy = render_taxonomy_for_scope(scope)
    fallback = "post_mood" if scope == "FEED" else "reel_mood"

    system = CLASSIFIER_SYSTEM_TEMPLATE.format(fallback=fallback)

    user_text = f"""Voici les descriptions des classes à appliquer :

{taxonomy}

NON NÉGOCIABLE - Suis cette procédure :
1. Examine la description du percepteur. Identifie les signaux visuels.
2. Décide la classe à partir du format dominant. Priorise les indices de structure, de composition, d'audio, de montage, de logo et de dispositif éditorial. Le sujet traité n'emporte la décision que s'il correspond aussi au format dominant ou à un signal obligatoire explicite de la classe.
3. Applique les SIGNAL_OBLIGATOIRE et EXCLUT des descriptions ci-dessus.
4. Si tu hésites entre deux classes, choisis celle dont le SIGNAL_OBLIGATOIRE matche le mieux.

Description du percepteur :
{alma_output}

Date de publication :
{posted_at or '(inconnue)'}

Caption du post :
{caption or '(pas de caption)'}"""

    tool = {
        "type": "function",
        "function": {
            "name": "classify",
            "description": "Classifie le post",
            "parameters": {
                "type": "object",
                "required": ["reasoning", "label"],
                "properties": {
                    "reasoning": {
                        "type": "string",
                        "description": "Raisonnement explicite",
                    },
                    "label": {
                        "type": "string",
                        "enum": labels,
                        "description": "Le format visuel du post",
                    },
                },
            },
        },
    }

    response = client.chat.completions.create(
        model=MODEL_CLASSIFIER,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
        tools=[tool],
        tool_choice={"type": "function", "function": {"name": "classify"}},
        temperature=0,
    )

    args = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
    return args.get("label", "?"), args.get("reasoning", "")


def main():
    import os
    os.environ["MILPO_TAXONOMY_DIR"] = "/Users/mathias/Desktop/Vaults/memoire-v2/Descriptions"

    conn = get_conn()
    client = get_client()
    client.timeout = 120.0

    # Charger les labels par scope
    from milpo.db import load_visual_formats
    labels_feed = [f["name"] for f in load_visual_formats(conn, "FEED")]
    labels_reels = [f["name"] for f in load_visual_formats(conn, "REELS")]

    # Dossier de traces
    traces_dir = Path(__file__).resolve().parent.parent / "data" / "traces_assist_test"
    traces_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Traces sauvegardées dans : {traces_dir}")

    # Charger les ground truth
    gt = {}
    for post_id in TEST_POSTS:
        row = conn.execute(
            "SELECT vf.name, p.caption, p.media_product_type, p.timestamp "
            "FROM annotations a "
            "JOIN visual_formats vf ON vf.id = a.visual_format_id "
            "JOIN posts p ON p.ig_media_id = a.ig_media_id "
            "WHERE a.ig_media_id = %s AND a.annotator = 'mathias'",
            (post_id,),
        ).fetchone()
        gt[post_id] = row

    results = []
    for i, post_id in enumerate(TEST_POSTS, 1):
        row = gt[post_id]
        scope = row["media_product_type"]
        expected = row["name"]
        caption = row["caption"]
        posted_at = row.get("timestamp")

        log.info(f"[{i}/10] {expected} ({scope}) — {post_id}")

        # Charger et signer les médias
        media_rows = conn.execute(
            "SELECT media_url, thumbnail_url, media_type, media_order "
            "FROM post_media WHERE parent_ig_media_id = %s ORDER BY media_order",
            (post_id,),
        ).fetchall()

        signed = gcs_sign_media([dict(m) for m in media_rows])

        if not signed:
            log.warning(f"  Pas de média, skip")
            continue

        # Étape 1 : Alma
        t0 = time.time()
        try:
            alma_output = call_alma(client, signed, caption, scope)
        except Exception as e:
            log.error(f"  Alma erreur : {e}")
            continue
        t_alma = time.time() - t0
        log.info(f"  Alma ({t_alma:.1f}s) :")
        for line in alma_output.strip().split("\n"):
            log.info(f"    {line}")

        # Étape 2 : Classifieur
        labels = labels_feed if scope == "FEED" else labels_reels
        t0 = time.time()
        try:
            predicted, reasoning = call_classifier(client, alma_output, caption, scope, labels, posted_at=posted_at)
        except Exception as e:
            log.error(f"  Classifieur erreur : {e}")
            continue
        t_clf = time.time() - t0

        match = predicted == expected
        symbol = "✓" if match else "✗"
        log.info(f"  Classifieur ({t_clf:.1f}s) : {predicted} {symbol}")
        if not match:
            log.info(f"  ATTENDU : {expected}")
        log.info(f"  Reasoning : {reasoning[:200]}")
        log.info("")

        trace = {
            "post_id": post_id,
            "scope": scope,
            "expected": expected,
            "predicted": predicted,
            "match": match,
            "alma_output": alma_output,
            "classifier_reasoning": reasoning,
            "caption": caption,
            "posted_at": str(posted_at) if posted_at else None,
            "latency_alma_s": round(t_alma, 1),
            "latency_classifier_s": round(t_clf, 1),
        }
        results.append(trace)

        # Sauvegarder la trace individuelle
        trace_file = traces_dir / f"{i:02d}_{expected}_{post_id}.json"
        with open(trace_file, "w", encoding="utf-8") as f:
            json.dump(trace, f, ensure_ascii=False, indent=2)

    # Résumé
    correct = sum(1 for r in results if r["match"])
    total = len(results)
    log.info("=" * 60)
    log.info(f"RÉSULTATS : {correct}/{total} ({100*correct/total:.0f}%)")
    log.info("=" * 60)
    for r in results:
        symbol = "✓" if r["match"] else "✗"
        log.info(f"  {symbol} {r['expected']:25s} → {r['predicted']}")

    # Erreurs détaillées
    errors = [r for r in results if not r["match"]]
    if errors:
        log.info(f"\n{'='*60}")
        log.info(f"ERREURS DÉTAILLÉES ({len(errors)})")
        log.info(f"{'='*60}")
        for r in errors:
            log.info(f"\nPost {r['post_id']} ({r['scope']})")
            log.info(f"  Attendu  : {r['expected']}")
            log.info(f"  Prédit   : {r['predicted']}")
            log.info(f"  Alma     : {r['alma_output'][:300]}")
            log.info(f"  Reasoning: {r['classifier_reasoning'][:300]}")

    # Sauvegarder le résumé complet
    summary = {
        "total": total,
        "correct": correct,
        "accuracy": round(100 * correct / total, 1) if total > 0 else 0,
        "results": results,
    }
    summary_file = traces_dir / "summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    log.info(f"\nTraces sauvegardées dans : {traces_dir}")

    conn.close()


if __name__ == "__main__":
    main()
