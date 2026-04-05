"""Test E2E du pipeline HILPO sur un post réel."""

from __future__ import annotations

import json
import sys

from hilpo.client import get_client
from hilpo.gcs import sign_media_urls
from hilpo.db import (
    get_conn,
    format_descriptions,
    insert_prompt_version,
    load_categories,
    load_dev_posts,
    load_post_media,
    load_strategies,
    load_visual_formats,
    store_api_call,
    store_prediction,
)
from hilpo.inference import PostInput, PromptSet, classify_post
from hilpo.prompts_v0 import PROMPTS_V0


def setup_prompts(conn) -> dict[tuple[str, str | None], int]:
    """Insère les prompts v0 en BDD si pas déjà présents. Retourne {(agent, scope): id}."""
    ids = {}
    for (agent, scope), content in PROMPTS_V0.items():
        # Vérifie si un prompt actif existe déjà
        if scope is None:
            existing = conn.execute(
                """
                SELECT id FROM prompt_versions
                WHERE agent = %s::agent_type
                  AND scope IS NULL
                  AND status = 'active'
                """,
                (agent,),
            ).fetchone()
        else:
            existing = conn.execute(
                """
                SELECT id FROM prompt_versions
                WHERE agent = %s::agent_type
                  AND scope = %s::media_product_type
                  AND status = 'active'
                """,
                (agent, scope),
            ).fetchone()

        if existing:
            ids[(agent, scope)] = existing["id"]
            print(f"  Prompt existant : {agent} × {scope or 'ALL'} (id={existing['id']})")
        else:
            pid = insert_prompt_version(conn, agent, scope, version=0, content=content)
            ids[(agent, scope)] = pid
            print(f"  Prompt créé : {agent} × {scope or 'ALL'} (id={pid})")

    return ids


def build_prompt_set(conn, scope: str) -> PromptSet:
    """Construit le PromptSet pour un scope donné."""
    vf = load_visual_formats(conn, scope)
    cats = load_categories(conn)
    strats = load_strategies(conn)

    return PromptSet(
        descriptor_instructions=PROMPTS_V0[("descriptor", scope)],
        category_instructions=PROMPTS_V0[("category", None)],
        visual_format_instructions=PROMPTS_V0[("visual_format", scope)],
        strategy_instructions=PROMPTS_V0[("strategy", None)],
        descriptor_descriptions=format_descriptions(vf),
        category_descriptions=format_descriptions(cats),
        visual_format_descriptions=format_descriptions(vf),
        strategy_descriptions=format_descriptions(strats),
    )


def main():
    conn = get_conn()
    client = get_client()

    print("=== HILPO Pipeline E2E Test ===\n")

    # 1. Setup prompts v0
    print("1. Setup prompts v0")
    prompt_ids = setup_prompts(conn)
    print()

    # 2. Charger un post dev
    print("2. Chargement d'un post dev")
    posts = load_dev_posts(conn, limit=1)
    if not posts:
        print("Aucun post dev trouvé !")
        sys.exit(1)

    post = posts[0]
    media = load_post_media(conn, post["ig_media_id"])

    print(f"  Post: {post['ig_media_id']}")
    print(f"  Type: {post['media_product_type']}")
    print(f"  Médias: {len(media)}")
    print(f"  Caption: {(post['caption'] or '')[:80]}...")
    print()

    # 3. Signer les URLs GCS
    print("  Signature des URLs GCS...")
    signed = sign_media_urls(media)
    if not signed:
        print("Aucun média avec URL trouvé !")
        sys.exit(1)

    media_urls = [url for url, _ in signed]
    media_types = [mtype for _, mtype in signed]
    print(f"  {len(signed)} URL(s) signée(s)")
    print()

    # 4. Construire le PromptSet
    scope = post["media_product_type"]
    prompt_set = build_prompt_set(conn, scope)

    # Labels pour les classifieurs
    vf = load_visual_formats(conn, scope)
    cats = load_categories(conn)
    strats = load_strategies(conn)

    vf_labels = [f["name"] for f in vf]
    cat_labels = [c["name"] for c in cats]
    strat_labels = [s["name"] for s in strats]

    # 5. Classifier !
    print("3. Classification en cours...")
    print(f"  Modèle descripteur: {scope}")
    print(f"  Labels visual_format: {len(vf_labels)} formats {scope}")
    print()

    post_input = PostInput(
        ig_media_id=post["ig_media_id"],
        media_product_type=scope,
        media_urls=media_urls,
        media_types=media_types,
        caption=post["caption"],
    )

    result = classify_post(
        post=post_input,
        prompts=prompt_set,
        category_labels=cat_labels,
        visual_format_labels=vf_labels,
        strategy_labels=strat_labels,
        client=client,
    )

    # 6. Afficher les résultats
    pred = result.prediction
    print("=== RÉSULTATS ===\n")
    print(f"  Catégorie     : {pred.category}")
    print(f"  Format visuel : {pred.visual_format}")
    print(f"  Stratégie     : {pred.strategy}")
    print()
    print(f"  Résumé visuel : {pred.features.resume_visuel[:200]}...")
    print()

    # 7. Métriques API
    print("=== API CALLS ===\n")
    for call in result.api_calls:
        print(f"  {call.agent:20s} | {call.input_tokens:6d} in | {call.output_tokens:5d} out | {call.latency_ms:5d}ms | {call.model}")
    print()
    print(f"  TOTAL: {result.total_input_tokens} in, {result.total_output_tokens} out, {result.total_latency_ms}ms")

    # 8. Stocker en BDD
    print("\n4. Stockage en BDD")
    for call in result.api_calls:
        agent_key = call.agent
        if agent_key == "descriptor":
            scope_key = scope
        elif agent_key == "visual_format":
            scope_key = scope
        else:
            scope_key = None

        prompt_id = prompt_ids.get((agent_key, scope_key))
        if not prompt_id and scope_key:
            prompt_id = prompt_ids.get((agent_key, None))

        store_api_call(
            conn,
            call_type="classification",
            agent=agent_key,
            model_name=call.model,
            prompt_version_id=prompt_id,
            ig_media_id=post["ig_media_id"],
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            cost_usd=None,
            latency_ms=call.latency_ms,
        )

    # Stocker les prédictions des classifieurs
    for axis in ("category", "visual_format", "strategy"):
        value = getattr(pred, axis)
        scope_key = scope if axis in ("descriptor", "visual_format") else None
        prompt_id = prompt_ids.get((axis, scope_key))
        if not prompt_id and scope_key:
            prompt_id = prompt_ids.get((axis, None))

        pid = store_prediction(
            conn,
            ig_media_id=post["ig_media_id"],
            agent=axis,
            prompt_version_id=prompt_id,
            predicted_value=value,
            raw_response=pred.features.model_dump() if axis == "visual_format" else None,
        )
        print(f"  Prediction {axis} stockée (id={pid})")

    # Stocker la sortie du descripteur (features, pas une classification)
    desc_prompt_id = prompt_ids[("descriptor", scope)]
    store_prediction(
        conn,
        ig_media_id=post["ig_media_id"],
        agent="descriptor",
        prompt_version_id=desc_prompt_id,
        predicted_value="features_extracted",
        raw_response=pred.features.model_dump(),
    )
    print(f"  Features descripteur stockées")

    conn.close()
    print("\n✓ Test E2E terminé !")


if __name__ == "__main__":
    main()
