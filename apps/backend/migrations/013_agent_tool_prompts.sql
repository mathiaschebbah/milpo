-- Migration 013: Versionnement des prompts de tools de la pipeline agentique A0
--
-- 4 prompts additionnels, tous dans agent='agent_executor' avec des sources distinctes :
-- - agent_tool_describe   : description du tool describe_media (envoyée à Haiku)
-- - agent_tool_taxonomy   : description du tool get_taxonomy
-- - agent_tool_examples   : description du tool get_examples
-- - agent_tool_desc_focus : system prompt Gemini pour describe_media(focus=...)

INSERT INTO prompt_versions (agent, scope, version, content, status, source)
VALUES
(
    'agent_executor', NULL, 0,
    E'Appelle le descripteur multimodal Gemini pour analyser le contenu visuel et audio du post Instagram courant.\n\n- Sans paramètre ''focus'' : retourne une description structurée complète (JSON avec features visuelles, audio, texte overlay, logos, mise en page, contenu principal, indices brand content, analyse caption).\n- Avec paramètre ''focus'' : retourne une réponse texte libre ciblée sur l''aspect demandé (ex: ''Décris l''audio et le contenu parlé en détail'', ''Quel texte exact vois-tu en overlay ?'', ''Décris les visuels slide par slide'').\n\nTu peux appeler ce tool plusieurs fois : d''abord sans focus pour la perception initiale, puis avec focus pour creuser un aspect spécifique.',
    'active',
    'agent_tool_describe'
),
(
    'agent_executor', NULL, 0,
    E'Récupère les descriptions taxonomiques pour un axe de classification. Chaque label est décrit avec ses critères discriminants.',
    'active',
    'agent_tool_taxonomy'
),
(
    'agent_executor', NULL, 0,
    E'Récupère des exemples annotés du dataset pour un label spécifique. Retourne des posts avec leur caption et annotation humaine (ground truth). Utilise ce tool quand tu hésites entre des labels proches pour voir des cas concrets.',
    'active',
    'agent_tool_examples'
),
(
    'agent_executor', NULL, 0,
    E'Tu es un analyste visuel et audio expert en contenus Instagram. Réponds de façon factuelle et concise à la question posée sur le média.',
    'active',
    'agent_tool_desc_focus'
);
