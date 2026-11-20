"""Auditable entity/term equivalence; no inferred geography or biography facts.

Aliases are vocabulary, not query patterns. A match must still occur in an
authorized source field. Parent institution matching requires the parent name
itself in that field; no speculative institute membership is added.
"""
import re

INSTITUTIONS = ({'canonical':'中国科学院',
    'aliases':('中国科学院','中科院','Chinese Academy of Sciences','CAS'),
    'source':'https://www.nssc.cas.cn/xxgk/gzzd/zkyzc/202111/t20211126_6272430.html'},)
TOPICS = ({'canonical':'AI4S',
    'aliases':('AI4S','AI4Science','AI for Science','Artificial Intelligence for Science'),
    'source':'https://arxiv.org/abs/2503.05822'},)


def contains(text, term):
    term=term.strip()
    if not term:return False
    if re.search(r'[A-Za-z]',term) and not re.search(r'[\u4e00-\u9fff]',term):
        pattern=re.escape(term).replace(r'\ ',r'\s+')
        return re.search(r'(?<![A-Za-z0-9])'+pattern+r'(?![A-Za-z0-9])',str(text),re.I) is not None
    return term.casefold() in str(text).casefold()


def aliases(value, *, institution=False):
    catalog=INSTITUTIONS if institution else TOPICS
    for entry in catalog:
        if any(value.strip().casefold()==alias.casefold() for alias in entry['aliases']):
            return list(entry['aliases'])
    return [value]


def expand(values, *, institution=False):
    return list(dict.fromkeys(alias for value in values for alias in aliases(value,institution=institution)))


def known_topic(value):
    return any(value.strip().casefold()==alias.casefold() for entry in TOPICS for alias in entry['aliases'])
