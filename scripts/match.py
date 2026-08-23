"""Fuzzy test-name matching used to link datasets from different source documents.

The same test is written differently across documents ("AFP" vs "Alpha-feto
protein (AFP)", "Beta Hydroxybutyrate" vs "b-hydroxybutyrate"). Matching runs
in tiers, most-confident first, so a cheap exact hit is never overridden by a
fuzzy one.
"""
import re
import unicodedata

# "ß" appears in this corpus as a beta glyph ("ß2 Microglobulin"), not as a
# German sharp s, so it expands to "beta" rather than "ss".
GREEK = {"α": "alpha", "β": "beta", "ß": "beta", "γ": "gamma", "δ": "delta",
         "µ": "micro", "μ": "micro"}

STOPWORDS = {"the", "of", "and", "for", "in", "to", "a", "test", "tests",
             "blood", "serum", "plasma", "total", "level", "levels"}

# Domain naming variants. Applied to folded text, longest phrase first.
SYNONYMS = [
    ("tri iodothyronine", "t3"),
    ("triiodothyronine", "t3"),
    ("thyroxine", "t4"),
    ("bloodspot", "blood spot"),
    ("phenobarbitone", "phenobarbital"),
    ("busulphan", "busulfan"),
    ("methyltransferase", "methyl transferase"),
    ("catecholamines", "catecholamine"),
    ("oestradiol", "estradiol"),
    ("sulphate", "sulfate"),
    ("faeces", "faecal"),
    ("faecal", "faecal"),
]


def fold(s: str) -> str:
    """Lowercase, de-accent, expand Greek letters, collapse to alphanumerics."""
    s = unicodedata.normalize("NFKC", s or "")
    for ch, rep in GREEK.items():
        s = s.replace(ch, rep)
    for ch in "‐‑‒–—−":
        s = s.replace(ch, "-")
    # Strip combining accents: "Müllerian" -> "Mullerian"
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9 ]+", " ", s.lower())
    s = re.sub(r"\s+", " ", s).strip()
    for a, b in SYNONYMS:
        s = re.sub(rf"\b{re.escape(a)}\b", b, s)
    return re.sub(r"\s+", " ", s).strip()


def squash(s: str) -> str:
    """Folded name with all separators removed: "NT-proBNP" -> "ntprobnp"."""
    return fold(s).replace(" ", "")


def bare(s: str) -> str:
    """Folded name with parenthetical content removed."""
    return fold(re.sub(r"\([^)]*\)", " ", s or ""))


def abbreviations(s: str) -> list[str]:
    """Short parenthetical tokens, which are usually the test's abbreviation."""
    out = []
    for grp in re.findall(r"\(([^)]{2,12})\)", s or ""):
        a = fold(grp)
        if a and " " not in a and not a.isdigit():
            out.append(a)
    return out


def tokens(s: str) -> frozenset:
    """Content tokens.

    Short tokens are KEPT: in lab naming a single character is often the entire
    discriminator ("vitamin d" vs "vitamin a", "free t3" vs "free t4"), so
    dropping them silently merges distinct tests.
    """
    return frozenset(t for t in fold(s).split() if t not in STOPWORDS)


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class Matcher:
    """Index a set of source records by name, then look candidates up."""

    def __init__(self, records, name_of=lambda r: r["test"]):
        self.records = list(records)
        self.name_of = name_of
        self.exact: dict[str, object] = {}
        self.squashed: dict[str, object] = {}
        self.loose: dict[str, object] = {}
        ambiguous_abbr: set[str] = set()

        for r in self.records:
            n = name_of(r)
            for k in (fold(n), bare(n)):
                if k:
                    self.exact.setdefault(k, r)
            for k in (squash(n), squash(bare(n))):
                if k:
                    self.squashed.setdefault(k, r)
            for a in abbreviations(n):
                if a in self.loose and self.loose[a] is not r:
                    ambiguous_abbr.add(a)   # shared abbreviation -> unusable
                self.loose.setdefault(a, r)
        for a in ambiguous_abbr:
            self.loose.pop(a, None)

        self._tokens = [(tokens(name_of(r)), r) for r in self.records]
        self.name_of = name_of

    def match(self, name: str, aliases=(), threshold: float = 0.75):
        """Return (record, how) or (None, None)."""
        candidates = [name, *aliases]

        for c in candidates:                       # tier 1: exact / bare
            for k in (fold(c), bare(c)):
                if k in self.exact:
                    return self.exact[k], "exact"

        for c in candidates:                       # tier 2: separator-insensitive
            for k in (squash(c), squash(bare(c))):
                if k and k in self.squashed:
                    return self.squashed[k], "squashed"

        for c in candidates:                       # tier 3: abbreviation
            k = fold(c)
            if k in self.loose:
                return self.loose[k], "abbreviation"
            for a in abbreviations(c):
                if a in self.loose:
                    return self.loose[a], "abbreviation"
            # A distinctive token may itself be the abbreviation ("eGfR").
            for tok in fold(c).split():
                if len(tok) >= 3 and tok not in STOPWORDS and tok in self.loose:
                    return self.loose[tok], "abbreviation"

        best, score, spread = None, 0.0, 10**6     # tier 4: token overlap
        for c in candidates:
            ct = tokens(c)
            if not ct:
                continue
            fc, bc = f" {fold(c)} ", f" {bare(c)} "
            for rt, r in self._tokens:
                j = jaccard(ct, rt)
                # Boost only when one name contains the other as a contiguous
                # PHRASE. Set containment alone is unsafe: {protein, c} is a
                # subset of {c, reactive, protein, crp}, but "Protein C" (a
                # coagulation factor) is not C-reactive protein.
                fr, br = f" {fold(self.name_of(r))} ", f" {bare(self.name_of(r))} "
                # The CONTAINED phrase must itself be at least two words.
                # A single word inside a longer name proves nothing: "creatinine"
                # sits inside "Albumin Creatinine Ratio" without being that test.
                phrase = any(len(a.split()) >= 2 and a in b
                             for a, b in ((fc, fr), (fr, fc), (bc, br), (br, bc)))
                if phrase and min(len(ct), len(rt)) >= 2:
                    j = max(j, 0.85)
                # Tie-break on the closest name, so "Vitamin D" prefers
                # "25-Hydroxy Vitamin D" over "1,25-Dihydroxy Vitamin D".
                d = len(ct ^ rt)
                if j > score or (j == score and d < spread):
                    best, score, spread = r, j, d
        if best is not None and score >= threshold:
            return best, f"fuzzy:{score:.2f}"
        return None, None
