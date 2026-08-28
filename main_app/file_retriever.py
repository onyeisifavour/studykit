"""
file_retriever.py

Consumes the Agent 2 file query spec manifest and the in-memory loaded topic
files, and produces the candidate question pool for downstream agents.

Adaptation (per AGENT2_WIRING_ISSUES_LOG): searches the in-memory topic files
via parse_bank_with_tags + extract_tags, matching each tier's
Subject/Topic/Type/Format tags — NOT hypothetical {type}_{format}.txt paths on
disk (the banks do not use that file layout).

Per-slot behaviour:
    - Try tiers in order (tier_1_exact → tier_2_topic_fallback →
      tier_3_type_relaxation).
    - Use the candidates from the FIRST tier that yields any match.
    - An empty candidate list is legitimate and flagged MISSING downstream.
"""

from __future__ import annotations

from .answer_matcher import parse_answer_bank, parse_bank_with_tags

TIER_ORDER = ('tier_1_exact', 'tier_2_topic_fallback', 'tier_3_type_relaxation')


def build_tag_index(topic_files: list[dict]) -> list[dict]:
    """
    Indexes every question in the loaded banks with its Subject/Topic/Type/
    Format tags. Falls back to the folder name when a tag is absent.
    """
    index: list[dict] = []
    for tf in topic_files:
        subject = tf.get('subject_name', '')
        topic = tf.get('topic_name', '')
        for entry in parse_bank_with_tags(tf.get('questions_text', '')):
            tags = entry['tags']
            index.append({
                'subject':       tags.get('Subject') or subject,
                'topic':         tags.get('Topic') or topic,
                'type':          tags.get('Type', ''),
                'format':        tags.get('Format', ''),
                'question_text': entry['question_text'],
                'number':        entry['number'],
                'source_topic':  topic,
                'source_subject': subject,
            })
    return index


def _matches_tier(entry: dict, tier: dict) -> bool:
    subject = tier.get('subject')
    if subject and entry['subject'].lower() != subject.lower():
        return False

    topic = tier.get('topic')
    if topic and entry['topic'].lower() != topic.lower():
        return False

    q_type = tier.get('type')
    if q_type and q_type.strip().upper() != 'ANY':
        if entry['type'].lower() != q_type.lower():
            return False

    fmt = tier.get('format')
    if fmt and entry['format'].lower() != fmt.lower():
        return False

    return True


def _keyword_hits(entries: list[dict], keywords: list[str]) -> list[dict]:
    if not keywords:
        return []
    lowered = [k.lower() for k in keywords if k and k.strip()]
    hits = []
    for e in entries:
        haystack = e['question_text'].lower()
        if any(k in haystack for k in lowered):
            hits.append(e)
    return hits


def retrieve_candidates(query_spec_manifest: dict, topic_files: list[dict]) -> dict:
    """
    Returns { slot_number: [candidate_dict, ...] }.

    candidate_dict shape:
        { question_text, tags, number, source_topic, source_subject, tier,
          answer_text }

    answer_text is looked up from the topic's paired answer bank by question
    number, so Agent 3 can embed the correct answer in its selection manifest
    without re-reading the bank files.

    An empty list per slot means no tier matched anything.
    """
    index = build_tag_index(topic_files)
    answer_lookup = _build_answer_lookup(topic_files)
    specs = query_spec_manifest.get('file_query_specs', [])
    pool: dict[int, list[dict]] = {}

    for spec in specs:
        slot = spec.get('slot_number')
        tiers = spec.get('search_tiers', {})
        chosen: list[dict] = []
        chosen_tier = None

        for tier_key in TIER_ORDER:
            tier = tiers.get(tier_key)
            if not isinstance(tier, dict):
                continue
            matches = [e for e in index if _matches_tier(e, tier)]
            if not matches:
                continue
            keywords = tier.get('search_keywords', [])
            kw = _keyword_hits(matches, keywords)
            if kw:
                chosen = kw
            else:
                chosen = matches
            chosen_tier = tier_key
            break

        pool[slot] = [
            {
                'question_text':   e['question_text'],
                'tags': {
                    'Subject': e['subject'],
                    'Topic':   e['topic'],
                    'Type':    e['type'],
                    'Format':  e['format'],
                },
                'number':          e['number'],
                'source_topic':    e['source_topic'],
                'source_subject':  e['source_subject'],
                'tier':            chosen_tier,
                'answer_text':     answer_lookup.get(
                    (e['source_topic'], e['number']), ''
                ),
            }
            for e in chosen
        ]

    return pool


def _build_answer_lookup(topic_files: list[dict]) -> dict[tuple[str, int], str]:
    """
    Builds {(topic_name, question_number): answer_text} from each topic's
    paired answer bank, so retrieval can attach answers to candidates.
    """
    lookup: dict[tuple[str, int], str] = {}
    for tf in topic_files:
        topic = tf.get('topic_name', '')
        for num, answer in parse_answer_bank(tf.get('answers_text', '')).items():
            lookup[(topic, num)] = answer
    return lookup
