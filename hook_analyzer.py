"""Extract winning ad-copy phrases (n-grams) from the corpus.

Surfaces the top phrases PH winners use so the user can stop guessing ad copy.
Pure Python — no LLM needed.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict


# Common English stopwords (compact list)
_STOP_EN = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "on", "at", "by", "for", "with", "from", "as", "or",
    "and", "but", "if", "this", "that", "these", "those", "it", "its",
    "you", "your", "yours", "yourself", "we", "our", "ours", "they", "them",
    "their", "i", "me", "my", "mine", "he", "she", "him", "her", "his", "hers",
    "do", "does", "did", "will", "would", "should", "could", "can", "may",
    "have", "has", "had", "having", "get", "got", "make", "made", "go",
    "all", "any", "both", "each", "few", "more", "most", "other", "some",
    "such", "no", "not", "only", "own", "same", "so", "than", "too", "very",
    "just", "now", "then", "out", "up", "down", "over", "under", "again",
    "here", "there", "when", "where", "why", "how", "what", "which", "who",
    "whom", "amp", "com", "ph", "us", "use", "using", "used", "new",
    "shop", "now", "buy", "learn", "more", "click", "free", "off", "save",
}

# Tagalog filler words to drop
_STOP_TL = {
    "ang", "ng", "nga", "po", "mga", "para", "ako", "kayo", "natin", "ninyo",
    "nila", "naman", "lang", "kasi", "pwede", "sana", "hindi", "ay", "sa",
    "na", "may", "ka", "ko", "ko'y", "siya", "nya", "niya", "kami", "yung",
    "kung", "pero", "din", "rin", "kaya", "muna", "ito", "iyan", "yan",
    "yun", "yung", "dito", "diyan", "doon", "mismo", "talaga", "din", "bang",
    "ba", "kase", "kase", "kahit", "alam", "ng", "para",
}

# Ad chrome / boilerplate to filter
_CHROME = {
    "shop now", "learn more", "buy now", "free shipping", "buy 1 take 1",
    "limited time", "cash on delivery", "for more details", "send us a message",
    "send us pm", "click the link", "link in bio", "tap the link",
    "available na", "available now", "out now", "order now",
}

_STOPWORDS = _STOP_EN | _STOP_TL

_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ]+(?:'[A-Za-zÀ-ÿ]+)?")
_URL_RE = re.compile(r"https?://\S+|www\.\S+|\S+\.com\S*|\S+\.ph\S*", re.IGNORECASE)

# URL/domain fragments that show up as tokens and should be filtered
_DOMAIN_TOKENS = {
    "https", "http", "www", "com", "ph", "net", "org", "shp", "ee",
    "shopee", "lazada", "tiktok", "fb", "facebook", "instagram", "tk",
}


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    # Strip URLs first to avoid 'https', 'shopee', 'com' polluting n-grams
    cleaned = _URL_RE.sub(" ", text)
    return [w.lower() for w in _WORD_RE.findall(cleaned)]


def _is_useful_phrase(tokens: tuple[str, ...]) -> bool:
    if not tokens:
        return False
    # Reject if all tokens are stopwords
    non_stop = [t for t in tokens if t not in _STOPWORDS]
    if len(non_stop) < max(1, len(tokens) - 1):
        return False
    # Reject if it's pure chrome
    phrase = " ".join(tokens)
    if phrase in _CHROME:
        return False
    # Reject pure numbers / single-letter words
    if all(len(t) <= 2 for t in tokens):
        return False
    # Reject any phrase containing URL/domain fragments
    if any(t in _DOMAIN_TOKENS for t in tokens):
        return False
    return True


def extract_phrases(
    ads: list[dict],
    n_range: tuple[int, int] = (2, 4),
    top_n: int = 30,
    min_count: int = 2,
    niche: str | None = None,
) -> list[dict]:
    """Returns top phrases used across winning ads.
    Each row: {phrase, count, niches{dict}, brands{set}, sample_ad_text}
    """
    n_min, n_max = n_range
    phrase_counter: Counter = Counter()
    phrase_niches: dict[str, Counter] = defaultdict(Counter)
    phrase_brands: dict[str, set] = defaultdict(set)
    phrase_samples: dict[str, str] = {}

    for ad in ads:
        if niche and ad.get("niche") != niche:
            continue
        text = ad.get("ad_text") or ""
        if not text:
            continue
        if ad.get("geo_signal") not in ("ph-confident", "ph-likely"):
            continue
        if ad.get("niche_relevance") == "no_match":
            continue
        if not ad.get("is_active"):
            continue
        if (ad.get("days_running") or 0) < 14:
            continue  # only count proven-ish ads

        tokens = _tokenize(text)
        for n in range(n_min, n_max + 1):
            for i in range(len(tokens) - n + 1):
                gram = tuple(tokens[i:i + n])
                if not _is_useful_phrase(gram):
                    continue
                p = " ".join(gram)
                phrase_counter[p] += 1
                phrase_niches[p][ad.get("niche") or "?"] += 1
                b = ad.get("brand") or ad.get("page_name")
                if b:
                    phrase_brands[p].add(b)
                if p not in phrase_samples:
                    phrase_samples[p] = (text[:160] + "…") if len(text) > 160 else text

    out: list[dict] = []
    for phrase, cnt in phrase_counter.most_common():
        if cnt < min_count:
            break
        # Require phrase to be used by >=2 distinct brands (otherwise it's one advertiser's idiosyncrasy)
        if len(phrase_brands[phrase]) < 2:
            continue
        out.append({
            "phrase": phrase,
            "count": cnt,
            "brands": len(phrase_brands[phrase]),
            "sample_brands": sorted(list(phrase_brands[phrase]))[:5],
            "top_niche": phrase_niches[phrase].most_common(1)[0][0] if phrase_niches[phrase] else "?",
            "niche_breakdown": dict(phrase_niches[phrase]),
            "sample_text": phrase_samples[phrase],
        })
        if len(out) >= top_n:
            break
    return out


def extract_phrases_by_longevity(
    ads: list[dict],
    n_range: tuple[int, int] = (2, 3),
    top_n: int = 20,
    min_count: int = 3,
    niche: str | None = None,
) -> dict[str, list[dict]]:
    """Bucket ads by longevity, then extract top phrases per bucket.

    Returns:
      {
        'evergreen': [...],  # ads with >=90 days running
        'proven':    [...],  # 30-89 days
        'losing':    [...],  # ads that stopped (inactive) with <30 days
      }

    The contrast between 'evergreen' and 'losing' shows you which copy patterns
    correlate with sustained winners versus quick-fail tests.
    """
    n_min, n_max = n_range

    def _phrases_in_bucket(bucket_ads: list[dict]) -> list[dict]:
        ctr: Counter = Counter()
        brand_set: dict[str, set] = defaultdict(set)
        sample: dict[str, str] = {}
        days_sum: dict[str, list[int]] = defaultdict(list)

        for ad in bucket_ads:
            text = ad.get("ad_text") or ""
            if not text:
                continue
            tokens = _tokenize(text)
            for n in range(n_min, n_max + 1):
                for i in range(len(tokens) - n + 1):
                    gram = tuple(tokens[i:i + n])
                    if not _is_useful_phrase(gram):
                        continue
                    p = " ".join(gram)
                    ctr[p] += 1
                    b = ad.get("brand") or ad.get("page_name")
                    if b:
                        brand_set[p].add(b)
                    if p not in sample:
                        sample[p] = (text[:140] + "…") if len(text) > 140 else text
                    days_sum[p].append(int(ad.get("days_running") or 0))

        bucket_out = []
        for phrase, cnt in ctr.most_common():
            if cnt < min_count:
                break
            if len(brand_set[phrase]) < 2:
                continue
            avg_days = sum(days_sum[phrase]) / len(days_sum[phrase]) if days_sum[phrase] else 0
            bucket_out.append({
                "phrase": phrase,
                "count": cnt,
                "brands": len(brand_set[phrase]),
                "avg_days": round(avg_days, 1),
                "sample_text": sample[phrase],
            })
            if len(bucket_out) >= top_n:
                break
        return bucket_out

    # Filter applicable ads (PH-confident, in-niche)
    filt_ads = []
    for a in ads:
        if niche and a.get("niche") != niche:
            continue
        if a.get("geo_signal") not in ("ph-confident", "ph-likely"):
            continue
        if a.get("niche_relevance") == "no_match":
            continue
        filt_ads.append(a)

    evergreen = [a for a in filt_ads if (a.get("days_running") or 0) >= 90 and a.get("is_active")]
    proven    = [a for a in filt_ads if 30 <= (a.get("days_running") or 0) < 90 and a.get("is_active")]
    losing    = [a for a in filt_ads if (a.get("days_running") or 0) < 30 and not a.get("is_active")]

    return {
        "evergreen": _phrases_in_bucket(evergreen),
        "proven":    _phrases_in_bucket(proven),
        "losing":    _phrases_in_bucket(losing),
        "_bucket_sizes": {
            "evergreen": len(evergreen),
            "proven": len(proven),
            "losing": len(losing),
        },
    }
