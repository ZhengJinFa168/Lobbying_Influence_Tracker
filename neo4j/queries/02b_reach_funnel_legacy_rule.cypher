// SENSITIVITY: reach funnel with the echo rule used until 2026-10-23 (verbatim, or implements / partial;
// recomputed from the judge's verdicts, without S12's cross-model downgrades). Headline rule: query 02, which reads the
// stored tiers: on a full run S10 precedes S12, so neither includes downgrades; after a partial re-run 02 does.
// Reach funnel (Track B), by user type:
//   chunks -> echoes -> echoes whose amendment survived into the EP report -> echoes whose amendment reached the law
// counted per echo (as in the plan) and per distinct amendment (robust to one amendment echoing many chunks),
// plus the base rate over all committee amendments. Shares are null for a user type with no echoes.
MATCH (o:Organisation)-[:SUBMITTED]->(:Comment {track:'B'})<-[:PART_OF]-(c:Chunk)
WITH o.user_type AS user_type, count(c) AS chunks
OPTIONAL MATCH (o2:Organisation {user_type: user_type})-[:SUBMITTED]->(:Comment {track:'B'})<-[:PART_OF]-(:Chunk)-[e:ECHOED_IN]->(a:Amendment)
WHERE (coalesce(e.verbatim, false) OR e.llm_relation IN ['implements','partial']) AND NOT coalesce(e.hidden, false)
WITH user_type, chunks, count(e) AS echoes,
     sum(CASE WHEN a.survived THEN 1 ELSE 0 END) AS echoes_survived,
     sum(CASE WHEN a.reached_law THEN 1 ELSE 0 END) AS echoes_reached_law, collect(DISTINCT a) AS ams
RETURN user_type, chunks, echoes, echoes_survived, echoes_reached_law,
       CASE WHEN echoes = 0 THEN null ELSE round(1.0 * echoes_survived / echoes, 3) END AS echo_share_survived,
       CASE WHEN echoes = 0 THEN null ELSE round(1.0 * echoes_reached_law / echoes, 3) END AS echo_share_reached_law,
       size(ams) AS amendments, size([a IN ams WHERE a.survived]) AS amendments_survived,
       size([a IN ams WHERE a.reached_law]) AS amendments_reached_law,
       CASE WHEN size(ams) = 0 THEN null ELSE round(1.0 * size([a IN ams WHERE a.survived]) / size(ams), 3) END AS amendment_share_survived,
       CASE WHEN size(ams) = 0 THEN null ELSE round(1.0 * size([a IN ams WHERE a.reached_law]) / size(ams), 3) END AS amendment_share_reached_law
UNION ALL
MATCH (a:Amendment)
WITH count(a) AS n, sum(CASE WHEN a.survived THEN 1 ELSE 0 END) AS s, sum(CASE WHEN a.reached_law THEN 1 ELSE 0 END) AS l
RETURN 'ALL_AMENDMENTS (base rate)' AS user_type, null AS chunks, null AS echoes, null AS echoes_survived,
       null AS echoes_reached_law, null AS echo_share_survived, null AS echo_share_reached_law,
       n AS amendments, s AS amendments_survived, l AS amendments_reached_law,
       round(1.0 * s / n, 3) AS amendment_share_survived, round(1.0 * l / n, 3) AS amendment_share_reached_law;
