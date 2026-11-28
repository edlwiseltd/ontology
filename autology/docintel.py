"""Document intelligence: from a specification to evidence-linked candidates, and from candidates to a proposal.

A research spike, **not in force**: nothing in the Engine, the API or Studio calls this module. It is used by its
tests and by ``deploy/make_docintel_benchmark.py``.

Four layers, kept apart on purpose:

1. **Sources.** A document's text is read (never fetched: links in it are kept as text), cut into paragraphs, and
   each paragraph gets an **anchor**: a stable identifier derived from its text, its section, its position and its
   character span in the normalised text. Quality problems are flagged, never repaired silently. Text that reads like
   an instruction to a program is flagged and left out of extraction: a document is data.
2. **Candidates.** A deterministic extractor reads each paragraph with generic English and French sentence patterns
   (definitions, composition, association with cardinality, states, transitions, approvals, prohibitions, values with
   units, references to standards) and proposes candidates. Every candidate cites the anchors it was read from, the
   pattern that read it, and whether it is *stated* by the text or *inferred* from context. No confidence number is
   invented: no calibrated estimator exists. Every candidate requires review.
3. **The evidence graph.** Mentions are normalised (case, plural, accents) into concepts; merges the extractor is not
   sure of (acronyms, near-duplicates) are **proposed**, with their rationale, and applied only by a person's
   decision. Competing readings are kept. The graph is not an ontology and holds no authority (``authoritative`` is
   always false).
4. **Mapping.** What the current model contract can express becomes an answer in the form of
   :data:`autology.architect.SCHEMA`, citing the anchors. That answer goes through :func:`autology.architect.propose`
   unchanged: the gateway's schema check, the citation check against the passages given, the strict loader. What
   cannot be expressed is returned as **unmapped findings** with the reason. Nothing is applied, stored or accepted,
   and by default every element is presented as needing a person's confirmation (see :func:`to_answer`).

The patterns hold no business vocabulary: they read sentence shapes and a small closed list of generic workflow
verbs. The extractor is a baseline for measurement, not a language model, and is presented as neither.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

CONTRACT = "docintel-1"
MAX_CHARS = 200_000
MAX_PARAGRAPHS = 2_000
ACCESS = ("public", "internal", "restricted")
BASES = ("stated", "inferred", "derived", "person", "unsupported")
NO_CONFIDENCE = "not estimated: the extractor has no calibrated estimator, so no number is given"


class DocumentError(ValueError):
    """A document that cannot be read safely; nothing was extracted from it."""


# ---------------------------------------------------------------------------------------------------- 1. sources
@dataclass(frozen=True)
class Anchor:
    id: str
    source: str
    section: str
    paragraph: int
    start: int
    end: int
    text: str
    language: str
    flags: Tuple[str, ...]

    def view(self) -> Dict[str, Any]:
        return {"id": self.id, "section": self.section, "paragraph": self.paragraph, "span": [self.start, self.end],
                "language": self.language, "flags": list(self.flags), "text": self.text}


STOP = {"en": {"the", "and", "of", "to", "is", "are", "each", "must", "be", "by", "with", "for", "an", "when", "which", "or"},
        "fr": {"le", "la", "les", "et", "de", "des", "du", "est", "sont", "chaque", "doit", "être", "par", "avec", "pour",
               "une", "un", "lorsque", "qui", "ou", "au", "aux"}}
# text that addresses a program rather than describing the subject; matched case-insensitively
INSTRUCTION = re.compile(
    r"\b(ignore (all |any )?(the )?(previous|prior|above) (instructions|rules)|disregard (the )?(previous|above)|"
    r"you are (now )?(an? )?(ai|assistant|model|chatgpt|claude)|system prompt|act as (an? )?(admin|administrator)|"
    r"grant (yourself|me|all) (all )?(permissions|rights|access)|ignorez (toutes )?les instructions|"
    r"oubliez (les|vos) (instructions|consignes)|tu es (maintenant )?(un )?(assistant|modèle))\b", re.I)
HEADING = re.compile(r"^(#{1,6}\s+(?P<md>.+)|(?P<num>\d+(\.\d+)*\.?)\s+(?P<title>[^\n]{2,80}))$")
BULLET = re.compile(r"^\s*([-*•–]|\d+[.)])\s+")


def _language(text: str) -> str:
    words = re.findall(r"[a-zàâçéèêëîïôûùüÿœ']+", text.lower())
    score = {lang: sum(1 for w in words if w in stop) for lang, stop in STOP.items()}
    if max(score.values()) < 2:
        return "unknown"
    return "fr" if score["fr"] > score["en"] else "en"


def read_source(text: str, source_id: str, *, title: str = "", source_type: str = "text", version: str = "",
                workspace: str, use_case: str = "", access: str = "internal", ingested_at: str = "",
                ingestion: str = "plain text, read as given") -> Dict[str, Any]:
    """One document as anchors. ``text`` is the document's text; nothing it mentions is opened or fetched."""
    if not isinstance(text, str):
        raise DocumentError("a document is read as text")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}", source_id or ""):
        raise DocumentError("source id: letters, digits, '.', '-' and '_' (at most 64)")
    if not workspace:
        raise DocumentError("a source belongs to one workspace")
    if access not in ACCESS:
        raise DocumentError(f"access: one of {', '.join(ACCESS)}")
    if len(text) > MAX_CHARS:
        raise DocumentError(f"the document is longer than {MAX_CHARS} characters: split it")
    control = sum(1 for c in text if unicodedata.category(c) == "Cc" and c not in "\n\r\t")
    if "\x00" in text or control > max(5, len(text) // 200):
        raise DocumentError("the text holds binary content: it is not read (a PDF must be turned into text first)")
    flags_doc: List[str] = []
    normal = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    repaired = re.sub(r"(\w)-\n(\w)", r"\1\2", normal)  # a word cut at a line end, as a PDF export leaves it
    if repaired != normal:
        flags_doc.append("words cut at a line end were joined")
    normal = repaired
    anchors: List[Anchor] = []
    seen: Dict[str, str] = {}
    section, position = "", 0
    blocks = re.split(r"\n\s*\n", normal)
    cursor = 0
    for block in blocks:
        start = normal.find(block, cursor)
        cursor = start + len(block)
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        heading = HEADING.match(lines[0].strip())
        if heading and len(lines) == 1 and not lines[0].rstrip().endswith("."):
            section = (heading.group("md") or f"{heading.group('num')} {heading.group('title')}").strip()
            continue
        # a list is read item by item: each item is a statement of its own
        pieces = [block] if not all(BULLET.match(ln) for ln in lines[1:] or ["-"]) or len(lines) == 1 else \
            ([lines[0]] if not BULLET.match(lines[0]) else []) + [ln for ln in lines if BULLET.match(ln)]
        for piece in pieces:
            body = piece.strip()
            if not body:
                continue
            offset = normal.find(piece, start)
            position += 1
            if position > MAX_PARAGRAPHS:
                raise DocumentError(f"more than {MAX_PARAGRAPHS} paragraphs: split the document")
            flags = []
            digest = hashlib.sha256(re.sub(r"\s+", " ", body.lower()).encode()).hexdigest()[:12]
            if digest in seen:
                flags.append(f"duplicate of {seen[digest]}")
            if body.count("|") >= 2 or "\t" in body:
                flags.append("table-like: columns may be mis-read")
            if re.search(r"https?://|www\.", body):
                flags.append("contains a link: not followed")
            if INSTRUCTION.search(body):
                flags.append("reads like an instruction to a program: kept as data, not extracted from")
            if len(body) < 12:
                flags.append("very short")
            anchor_id = f"{source_id}#{digest}" if digest not in seen else f"{source_id}#{digest}-{position}"
            seen.setdefault(digest, anchor_id)
            anchors.append(Anchor(anchor_id, source_id, section, position, offset, offset + len(piece),
                                  re.sub(r"\s+", " ", BULLET.sub("", body)), _language(body), tuple(flags)))
    language = _language(normal)
    return {"contract": CONTRACT, "id": source_id, "title": title, "type": source_type, "version": version,
            "workspace": workspace, "use_case": use_case, "access": access,
            "content_sha256": hashlib.sha256(normal.encode()).hexdigest(), "characters": len(normal),
            "language": language, "ingestion": {"method": ingestion, "at": ingested_at, "tool": f"autology.docintel {CONTRACT}"},
            "quality": flags_doc + ([] if anchors else ["no paragraph could be read"]),
            "anchors": [a.view() for a in anchors],
            "limits": ["plain text only: tables, images and page layout are not interpreted",
                       "a page number is not known unless the text carries it"]}


# ------------------------------------------------------------------------------------------------- 2. candidates
DET_EN = r"(?:the|a|an|each|every|one|any|all)"
DET_FR = r"(?:(?:chaque|toute|tout|une|un|les|le|la|des|du|de la)\b|l'|de l')"
STOPS = (r"is|are|was|were|has|have|must|may|can|should|shall|consists|contains|includes|belongs|moves|stays|runs|"
         r"est|sont|a|ont|doit|peut|comprend|contient|se|passe|"
         r"of|du|des|by|par|to|à|and|et|or|ou|when|lorsque|with|avec|for|at|on|in|into|from|over|under|between|within|"
         r"during|after|before|per|about|without|pour|sur|dans|entre|avec|sans|après|avant|chez|vers|selon|"
         r"the|a|an|le|la|les|un|une|each|every|its|their|this|that|these|those|which|who|ce|cette|ces|qui|que|"
         r"fairly|only|also|then|always|never|not|ne|pas|jamais|years?|time")
NP = (r"(?!(?:" + STOPS + r")\b)[A-Za-zÀ-ÿ][\w'À-ÿ\-]*(?:(?: de| d')? (?!(?:" + STOPS + r")\b)[\w'À-ÿ\-]+(?<!ly)){0,3}")
# generic workflow verbs only (closed lists); the object of the verb comes from the text
VERBS_EN = ("approve", "approves", "reject", "rejects", "validate", "validates", "check", "checks", "verify", "verifies",
            "issue", "issues", "create", "creates", "record", "records", "register", "registers", "submit", "submits",
            "assign", "assigns", "close", "closes", "cancel", "cancels", "ship", "ships", "receive", "receives",
            "inspect", "inspects", "sign", "signs", "publish", "publishes", "send", "sends", "review", "reviews",
            "allocate", "allocates", "release", "releases", "archive", "archives", "schedule", "schedules")
VERBS_FR = ("approuve", "rejette", "valide", "vérifie", "contrôle", "émet", "crée", "enregistre", "soumet", "affecte",
            "clôture", "annule", "expédie", "réceptionne", "inspecte", "signe", "publie", "envoie", "examine", "attribue",
            "libère", "archive", "planifie", "traite", "qualifie")
CARD_EN = {"one": "1", "a": "1", "an": "1", "exactly one": "1", "one or more": "1..*", "at least one": "1..*",
           "several": "0..*", "many": "0..*", "zero or more": "0..*", "any number of": "0..*", "at most one": "0..1",
           "zero or one": "0..1", "an optional": "0..1", "two": "2", "three": "3"}
CARD_FR = {"un": "1", "une": "1", "un seul": "1", "une seule": "1", "un ou plusieurs": "1..*", "une ou plusieurs": "1..*",
           "au moins un": "1..*", "au moins une": "1..*", "plusieurs": "0..*", "zéro ou plusieurs": "0..*",
           "au plus un": "0..1", "au plus une": "0..1", "deux": "2", "trois": "3"}
UNITS = r"(mm|cm|m|km|kg|g|t|°C|K|bar|Pa|kPa|MPa|kW|W|V|A|Hz|h|min|s|days?|jours?|heures?|%|EUR|€|USD|\$|L|ml)"
STANDARD = re.compile(r"\b((?:ISO|IEC|EN|NF|IEEE|DIN|ASTM|ANSI|BS|RFC)(?:[ /-](?:IEC|EN|ISO))?[ -]?\d{2,6}(?:[-:]\d+)*)\b")


def _key(label: str) -> str:
    """The normalised form two mentions must share to be one concept: case, accents, plural and spacing removed."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", label.lower()) if not unicodedata.combining(c))
    words = [w for w in re.split(r"[^a-z0-9]+", plain) if w and w not in ("the", "a", "an", "le", "la", "les", "un", "une", "l")]
    out = []
    for w in words:
        if len(w) > 4 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 4 and w.endswith(("sses", "ches", "shes", "xes")):
            w = w[:-2]
        elif len(w) > 3 and w.endswith(("s", "x")) and not w.endswith(("ss", "us", "is")):
            w = w[:-1]
        out.append(w)
    return " ".join(out)


QUANTIFIERS = r"(?:several|many|some|one or more|zero or more|two|three|four|plusieurs|quelques|deux|trois|quatre|un ou plusieurs|une ou plusieurs)"


def _clean(np: str) -> str:
    np = re.sub(r"^(?:(?:the|an|a|each|every|one|any|all|chaque|toute|tout|une|un|les|le|la|des|du|de la)\s+|l'|d'|de l')", "",
                np.strip(" .,:;"), flags=re.I)
    np = re.sub(rf"^{QUANTIFIERS}\s+", "", np, flags=re.I)
    return re.sub(r"\s+", " ", np).strip(" .,:;'")


def _split_list(text: str) -> List[str]:
    parts = re.split(r",\s*|\s+(?:and|or|et|ou)\s+", text.strip(" .;:"))
    return [_clean(p) for p in parts if _clean(p)]


def _snake(label: str) -> str:
    plain = "".join(c for c in unicodedata.normalize("NFKD", label) if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z0-9]+", "_", plain).strip("_").lower()[:60] or "x"


def _camel(label: str) -> str:
    plain = "".join(c for c in unicodedata.normalize("NFKD", label) if not unicodedata.combining(c))
    return "".join(w[:1].upper() + w[1:] for w in re.split(r"[^A-Za-z0-9]+", plain) if w)[:60] or "X"


def _evidence(anchor: Mapping[str, Any], match: re.Match) -> Dict[str, Any]:
    return {"anchor": anchor["id"], "span": [match.start(), match.end()], "quote": match.group(0)[:300]}


def extract(sources: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Candidates read from the sources' anchors, each citing where it was read. Sources of different workspaces
    are never read together: an evidence graph belongs to one workspace."""
    scopes = {s["workspace"] for s in sources}
    if len(scopes) > 1:
        raise DocumentError("sources of different workspaces are never read into one graph")
    mentions: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []

    def add(kind: str, method: str, basis: str, ev: Dict[str, Any], **data: Any) -> None:
        mentions.append({"kind": kind, "method": method, "basis": basis, "evidence": [ev], **data})

    for source in sources:
        for anchor in source["anchors"]:
            if any(f.startswith("reads like an instruction") for f in anchor["flags"]):
                skipped.append({"anchor": anchor["id"], "why": "reads like an instruction to a program"})
                continue
            if any(f.startswith("duplicate of") for f in anchor["flags"]):
                skipped.append({"anchor": anchor["id"], "why": anchor["flags"][0]})
                continue
            text, lang = anchor["text"], anchor["language"]
            for sentence in re.split(r"(?<=[.;!?])\s+", text):
                for clause in re.split(r",\s+(?:and|et|but|mais)\s+(?=(?:each|every|a|an|the|chaque|un|une|le|la|les)\b)", sentence, flags=re.I):
                    _read(clause, anchor, lang, add)
    return {"contract": CONTRACT, "workspace": next(iter(scopes), None), "mentions": mentions, "skipped": skipped}


def _read(s: str, anchor: Mapping[str, Any], lang: str, add: Any) -> None:  # noqa: C901 - one table of patterns
    fr = lang == "fr"
    # references to standards: document references, never ontology concepts
    for m in STANDARD.finditer(s):
        add("reference", "pattern:standard", "stated", _evidence(anchor, m), label=m.group(1))
    # acronyms: "Long Name (LN)"
    for m in re.finditer(r"\b((?:[A-ZÀ-Ý][\w'À-ÿ\-]*\s+){1,4}[\w'À-ÿ\-]+)\s+\(([A-Z]{2,6})\)", s):
        add("alias", "pattern:acronym", "stated", _evidence(anchor, m), label=m.group(1).strip(), alias=m.group(2))
    # values with units: kept as written, never converted
    for m in re.finditer(rf"(?<![\w.])(\d+(?:[ .,]\d{{3}})*(?:[.,]\d+)?)\s?{UNITS}(?![\w])", s):
        add("value", "pattern:value-with-unit", "stated", _evidence(anchor, m), label=m.group(0).strip())
    det, verbs = (DET_FR, VERBS_FR) if fr else (DET_EN, VERBS_EN)
    if not fr:
        patterns = [
            ("specialization", rf"^(?:{det}\s+)?(?P<a>{NP})\s+(?:is|are)\s+(?:a|an)\s+(?:kind|type|sort)\s+of\s+(?P<b>{NP})"),
            ("definition", rf"^(?:{det}\s+)?(?P<a>{NP})\s+(?:is|are)\s+(?:a|an|the)\s+(?P<b>{NP})"),
            ("composition", rf"^(?:{det}\s+)?(?P<a>{NP})\s+(?:consists of|is composed of|is made of|contains|includes)\s+(?P<list>.+?)\.?$"),
            ("association", rf"^(?:{det}\s+)?(?P<a>{NP})\s+(?P<verb>has|have|belongs to|is assigned to|refers to|references|is linked to|is attached to|concerns)\s+(?P<card>exactly one|one or more|at least one|zero or more|at most one|zero or one|any number of|an optional|several|many|one|two|three|a|an)\s+(?P<b>{NP})"),
            ("states", rf"^(?:the\s+)?(?:status|state)\s+of\s+(?:{det}\s+)?(?P<a>{NP})\s+(?:is one of|can be|is)\s*:?\s*(?P<list>.+?)\.?$"),
            ("states", rf"^(?:{det}\s+)?(?P<a>{NP})\s+(?:can be|is either|moves through(?: the states)?)\s*:?\s*(?P<list>(?:[\w\-]+,\s*)+[\w\-]+,?\s+(?:or|and|then)\s+[\w\-]+)\.?$"),
            ("transition", rf"^(?:{det}\s+)?(?P<a>{NP})\s+(?:moves|goes|passes)\s+from\s+(?P<from>[\w\-]+)\s+to\s+(?P<to>[\w\-]+)(?:\s+when\s+(?P<when>.+?))?\.?$"),
            ("approval", rf"^(?:{det}\s+)?(?P<a>{NP})(?:\s+[^,.;]*?)?\s+must be (?:approved|signed off|validated|authorised|authorized) by\s+(?:{det}\s+)?(?P<role>{NP})(?P<cond>\s+(?:when|if|above|over|beyond)\s+.+?)?\.?$"),
            ("access", rf"^only\s+(?:{det}\s+)?(?P<role>{NP})\s+(?:may|can)\s+(?P<verb>\w+)\s+(?:{det}\s+)?(?P<a>{NP})"),
            ("prohibition", rf"^(?:{det}\s+)?(?P<a>{NP})(?:\s+[^,.;]*?)?\s+(?:must not|may not|cannot|must never|is never)\s+(?P<what>.+?)\.?$"),
            ("action", rf"^(?:{det}\s+)?(?P<role>{NP})\s+(?P<verb>{'|'.join(verbs)})\s+(?:{det}\s+)?(?P<a>{NP})"),
        ]
        cards = CARD_EN
    else:
        patterns = [
            ("specialization", rf"^(?:{det}\s*)?(?P<a>{NP})\s+(?:est|sont)\s+(?:un|une)\s+(?:sorte|type|forme)\s+de\s+(?P<b>{NP})"),
            ("definition", rf"^(?:{det}\s*)?(?P<a>{NP})\s+(?:est|sont)\s+(?:un|une|le|la)\s+(?P<b>{NP})"),
            ("composition", rf"^(?:{det}\s*)?(?P<a>{NP})\s+(?:se compose de|est composée? de|comprend|contient|inclut)\s+(?P<list>.+?)\.?$"),
            ("association", rf"^(?:{det}\s*)?(?P<a>{NP})\s+(?P<verb>a|possède|appartient à|est affectée? à|concerne|se rapporte à|référence)\s+(?P<card>un ou plusieurs|une ou plusieurs|au moins une?|zéro ou plusieurs|au plus une?|un seul|une seule|plusieurs|deux|trois|un|une)\s+(?P<b>{NP})"),
            ("states", rf"^(?:le\s+)?(?:statut|état)\s+(?:d'(?:une?\s+)?|de\s+(?:la\s+|l'|une?\s+)?|du\s+)(?P<a>{NP})\s+(?:est|peut être)\s*(?:l'un des suivants)?\s*:?\s*(?P<list>.+?)\.?$"),
            ("states", rf"^(?:{det}\s*)?(?P<a>{NP})\s+peut être\s*:?\s*(?P<list>(?:[\w\-À-ÿ]+,\s*)+[\w\-À-ÿ]+,?\s+(?:ou|et|puis)\s+[\w\-À-ÿ]+)\.?$"),
            ("transition", rf"^(?:{det}\s*)?(?P<a>{NP})\s+passe\s+de\s+(?:l'état\s+)?«?\s*(?P<from>[\w\-À-ÿ]+)\s*»?\s+à\s+(?:l'état\s+)?«?\s*(?P<to>[\w\-À-ÿ]+)\s*»?(?:\s+lorsque\s+(?P<when>.+?))?\.?$"),
            ("approval", rf"^(?:{det}\s*)?(?P<a>{NP})(?:\s+[^,.;]*?)?\s+doit être (?:approuvée?|validée?|signée?|autorisée?) par\s+(?:{det}\s*)?(?P<role>{NP})(?P<cond>\s+(?:lorsque|si|au-delà de|au-dessus de)\s+.+?)?\.?$"),
            ("access", rf"^seule?s?\s+(?:{det}\s*)?(?P<role>{NP})\s+peu(?:t|vent)\s+(?P<verb>\w+)\s+(?:{det}\s*)?(?P<a>{NP})"),
            ("prohibition", rf"^(?:{det}\s*)?(?P<a>{NP})(?:\s+[^,.;]*?)?\s+ne (?:doit|peut) (?:jamais |pas )(?P<what>.+?)\.?$"),
            ("action", rf"^(?:{det}\s*)?(?P<role>{NP})\s+(?P<verb>{'|'.join(verbs)})\s+(?:{det}\s*)?(?P<a>{NP})"),
        ]
        cards = CARD_FR
    for kind, pattern in patterns:
        found = re.search(pattern, s.strip(), flags=re.I)
        if not found:
            continue
        m = found
        ev = _evidence(anchor, m)
        a = _clean(m.group("a")) if "a" in m.groupdict() and m.group("a") else ""
        if kind == "specialization":
            add("concept", f"pattern:{lang}:specialization", "stated", ev, label=a)
            add("concept", f"pattern:{lang}:specialization", "stated", ev, label=_clean(m.group("b")))
            add("relation", f"pattern:{lang}:specialization", "stated", ev, relation="specialization", source=a,
                target=_clean(m.group("b")), verb="is a kind of", cardinality=None)
            return
        if kind == "definition":
            add("concept", f"pattern:{lang}:definition", "stated", ev, label=a, definition=s.strip()[:300])
            continue
        if kind == "composition":
            add("concept", f"pattern:{lang}:composition", "stated", ev, label=a)
            for part in _split_list(m.group("list")):
                add("concept", f"pattern:{lang}:composition", "stated", ev, label=part)
                add("relation", f"pattern:{lang}:composition", "stated", ev, relation="composition", source=a,
                    target=part, verb="contains", cardinality="1..*")
            return
        if kind == "association":
            b = _clean(m.group("b"))
            add("concept", f"pattern:{lang}:association", "stated", ev, label=a)
            add("concept", f"pattern:{lang}:association", "stated", ev, label=b)
            add("relation", f"pattern:{lang}:association", "stated", ev, relation="association", source=a, target=b,
                verb=m.group("verb").lower(), cardinality=cards.get(m.group("card").lower()))
            return
        if kind == "states":
            add("concept", f"pattern:{lang}:states", "stated", ev, label=a)
            add("states", f"pattern:{lang}:states", "stated", ev, label=a,
                states=[_snake(x) for x in _split_list(m.group("list"))])
            return
        if kind == "transition":
            add("transition", f"pattern:{lang}:transition", "stated", ev, label=a, from_state=_snake(m.group("from")),
                to_state=_snake(m.group("to")), when=(m.group("when") or "").strip()[:200])
            return
        if kind == "approval":
            add("concept", f"pattern:{lang}:approval", "stated", ev, label=a)
            add("role", f"pattern:{lang}:approval", "stated", ev, label=_clean(m.group("role")))
            add("rule", f"pattern:{lang}:approval", "stated", ev, rule="approval", label=a, role=_clean(m.group("role")),
                condition=(m.group("cond") or "").strip()[:200], safety=True)
            return
        if kind == "access":
            add("role", f"pattern:{lang}:access", "stated", ev, label=_clean(m.group("role")))
            add("rule", f"pattern:{lang}:access", "stated", ev, rule="access", label=a, role=_clean(m.group("role")),
                verb=m.group("verb").lower(), safety=True)
            return
        if kind == "prohibition":
            add("rule", f"pattern:{lang}:prohibition", "stated", ev, rule="prohibition", label=a,
                condition=m.group("what").strip()[:200], safety=True)
            return
        if kind == "action":
            add("role", f"pattern:{lang}:action", "inferred", ev, label=_clean(m.group("role")))
            add("concept", f"pattern:{lang}:action", "stated", ev, label=a)
            add("action", f"pattern:{lang}:action", "stated", ev, label=a, role=_clean(m.group("role")),
                verb=m.group("verb").lower())
            return


# ---------------------------------------------------------------------------------------------- 3. evidence graph
def _near(a: str, b: str) -> bool:
    if a == b or min(len(a), len(b)) < 5:
        return False
    if a in b.split() or b in a.split():
        return True
    # one edit apart, for words of some length (a typing error, a missing letter)
    if abs(len(a) - len(b)) > 1:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] <= 1


def graph(extracted: Mapping[str, Any], decisions: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """The evidence graph: concepts with their mentions, relations, states, rules, actions, references and the merges
    that are only proposed. ``decisions`` maps a merge id to ``accept`` or ``reject`` (a person's choice); a merge
    that nobody accepted is not applied."""
    decisions = dict(decisions or {})
    mentions = extracted["mentions"]
    kinds_of: Dict[str, set] = {}
    for m in mentions:
        if m["kind"] in ("concept", "role"):
            kinds_of.setdefault(_key(m["label"]), set()).add(m["kind"])
    nodes: Dict[str, Dict[str, Any]] = {}

    def node(label: str, kind: str, m: Mapping[str, Any]) -> str:
        key = _key(label)
        nid = f"{kind}:{key}"
        n = nodes.setdefault(nid, {"id": nid, "kind": kind, "key": key, "labels": [], "mentions": [], "methods": [],
                                    "basis": "stated", "definitions": [], "requires_review": True, "confidence": None})
        if label not in n["labels"]:
            n["labels"].append(label)
        n["mentions"] += m["evidence"]
        if m["method"] not in n["methods"]:
            n["methods"].append(m["method"])
        if m.get("definition"):
            n["definitions"].append(m["definition"])
        return nid

    relations: List[Dict[str, Any]] = []
    states: Dict[str, Dict[str, Any]] = {}
    transitions: List[Dict[str, Any]] = []
    rules: List[Dict[str, Any]] = []
    actions: List[Dict[str, Any]] = []
    references: List[Dict[str, Any]] = []
    values: List[Dict[str, Any]] = []
    aliases: List[Dict[str, Any]] = []
    for m in mentions:
        k = m["kind"]
        if k in ("concept", "role"):
            node(m["label"], k, m)
        elif k == "relation":
            relations.append({"type": m["relation"], "from": f"concept:{_key(m['source'])}", "to": f"concept:{_key(m['target'])}",
                              "verb": m["verb"], "cardinality": m["cardinality"], "evidence": m["evidence"],
                              "method": m["method"], "basis": m["basis"], "requires_review": True})
        elif k == "states":
            entry = states.setdefault(f"concept:{_key(m['label'])}", {"readings": []})
            entry["readings"].append({"states": m["states"], "evidence": m["evidence"], "method": m["method"]})
        elif k == "transition":
            transitions.append({"concept": f"concept:{_key(m['label'])}", "from": m["from_state"], "to": m["to_state"],
                                "when": m["when"], "evidence": m["evidence"], "method": m["method"]})
        elif k == "rule":
            rules.append({"rule": m["rule"], "concept": f"concept:{_key(m['label'])}",
                          "role": f"role:{_key(m['role'])}" if m.get("role") else None, "condition": m.get("condition", ""),
                          "verb": m.get("verb"), "evidence": m["evidence"], "method": m["method"], "safety": True,
                          "requires_review": True})
        elif k == "action":
            actions.append({"verb": m["verb"], "object": f"concept:{_key(m['label'])}", "role": f"role:{_key(m['role'])}",
                            "evidence": m["evidence"], "method": m["method"], "basis": "stated", "requires_review": True})
        elif k == "reference":
            references.append({"label": m["label"], "evidence": m["evidence"]})
        elif k == "value":
            values.append({"label": m["label"], "evidence": m["evidence"]})
        elif k == "alias":
            aliases.append(m)
    # a word read as a role somewhere and as a thing elsewhere: both readings are kept, and the conflict is said
    ambiguities = [{"key": key, "why": "read as a role and as a concept", "readings": sorted(kinds)}
                   for key, kinds in kinds_of.items() if len(kinds) > 1]
    for cid, entry in states.items():
        distinct = {tuple(r["states"]) for r in entry["readings"]}
        if len(distinct) > 1:
            ambiguities.append({"key": cid, "why": "the states are listed differently in different places",
                                "readings": [list(d) for d in sorted(distinct)]})
    pairs: Dict[Tuple[str, str], set] = {}
    for r in relations:
        pairs.setdefault((r["from"], r["to"]), set()).add((r["type"], r["cardinality"]))
    ambiguities += [{"key": f"{a} -> {b}", "why": "the same pair is related in different ways", "readings": sorted(map(str, v))}
                    for (a, b), v in pairs.items() if len(v) > 1]
    # merges the extractor is not sure of: proposed with their rationale, never applied without a person
    merges = []
    concept_ids = sorted(n for n in nodes if n.startswith("concept:"))
    for a in aliases:
        full, short = f"concept:{_key(a['label'])}", f"concept:{_key(a['alias'])}"
        merges.append({"id": f"merge:{_key(a['alias'])}={_key(a['label'])}", "members": [full, short],
                       "why": f"'{a['alias']}' is introduced as the short form of '{a['label']}'", "evidence": a["evidence"],
                       "kind": "acronym"})
    for i, x in enumerate(concept_ids):
        for y in concept_ids[i + 1:]:
            if _near(nodes[x]["key"], nodes[y]["key"]):
                merges.append({"id": f"merge:{nodes[x]['key']}={nodes[y]['key']}", "members": [x, y], "kind": "near-duplicate",
                               "why": "one name contains the other, or they differ by one letter: perhaps the same thing",
                               "evidence": nodes[x]["mentions"][:1] + nodes[y]["mentions"][:1]})
    for merge in merges:
        merge["decision"] = decisions.get(merge["id"], "proposed")
        kinds = {mid.split(":", 1)[0] for mid in merge["members"]}
        if len(kinds) > 1:
            merge["decision"] = "refused: members of different kinds are never merged"
    rename = {}
    for merge in merges:
        if merge["decision"] == "accept":
            present = [mm for mm in merge["members"] if mm in nodes]
            if not present:
                continue
            keep = merge["members"][0]
            if keep not in nodes:  # the full name was only read inside the acronym's sentence: it becomes the concept's name
                moved = nodes.pop(present[0])
                nodes[keep] = {**moved, "id": keep, "key": keep.split(":", 1)[1],
                               "labels": [merge["why"].split("'")[3]] + moved["labels"],
                               "merged": moved.get("merged", []) + [{"from": present[0], "decision": merge["id"]}]}
                rename[present[0]] = keep
                present = [keep] + present[1:]
            rest = [mm for mm in present if mm != keep]
            for other in rest:
                rename[other] = keep
                nodes[keep]["labels"] += [l for l in nodes[other]["labels"] if l not in nodes[keep]["labels"]]
                nodes[keep]["mentions"] += nodes[other]["mentions"]
                nodes[keep]["merged"] = nodes[keep].get("merged", []) + [{"from": other, "decision": merge["id"]}]
                del nodes[other]
    for r in relations:
        r["from"], r["to"] = rename.get(r["from"], r["from"]), rename.get(r["to"], r["to"])
    for n in nodes.values():
        n["mentions"] = list({json.dumps(e, sort_keys=True): e for e in n["mentions"]}.values())
        if len(n["labels"]) > 1:
            n["basis"] = "derived"   # one concept from several written forms: the grouping is the normaliser's
    return {"contract": CONTRACT, "authoritative": False, "workspace": extracted["workspace"],
            "note": "candidates read from documents: not business facts, not model elements; each requires review",
            "nodes": sorted(nodes.values(), key=lambda n: n["id"]), "relations": relations,
            "states": states, "transitions": transitions, "rules": rules, "actions": actions,
            "references": references, "values": values, "merges": merges, "ambiguities": ambiguities,
            "skipped": extracted["skipped"], "confidence": NO_CONFIDENCE}


def redact(evidence_graph: Mapping[str, Any], sources: Sequence[Mapping[str, Any]], may_read: Iterable[str]) -> Dict[str, Any]:
    """The graph as a caller who may read only the sources ``may_read`` sees it: quotes from other sources are
    withheld (the candidate stays, its excerpt does not)."""
    allowed = set(may_read)
    owner = {a["id"]: s["id"] for s in sources for a in s["anchors"]}
    out = json.loads(json.dumps(evidence_graph))

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if "anchor" in value and "quote" in value and owner.get(value["anchor"]) not in allowed:
                value["quote"] = "withheld: you may not read this source"
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
    walk(out)
    return out


# ------------------------------------------------------------------------------------------------------ 4. mapping
TYPE_HINTS = (("number", r"\b(amount|quantity|count|number|weight|price|cost|total|rate|pressure|temperature|duration|"
                         r"montant|quantité|nombre|poids|prix|coût|taux|pression|température|durée)\b"),
              ("date", r"\b(date|deadline|due|échéance)\b"))


def _attribute_type(label: str) -> str:
    for kind, pattern in TYPE_HINTS:
        if re.search(pattern, label, re.I):
            return kind
    return "string"


def to_answer(evidence_graph: Mapping[str, Any], stated_as_supplied: bool = False) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """An answer in the form of :data:`autology.architect.SCHEMA`, citing anchors, and the findings it cannot hold.
    Deterministic: the same graph gives the same answer.

    **Fail-closed by default:** every element is presented as ``inferred``, so the Engine keeps it out of a draft
    until a person confirms it, even when a document states it. A pattern can misread a sentence, and a reading by a
    machine is not a person's statement. The paragraph is still cited, and the graph keeps "stated". Whether a
    document's statements may count as stated is an owner decision (DI-1); ``stated_as_supplied`` exists to measure
    it, and nothing in force passes it."""
    basis = "supplied" if stated_as_supplied else "inferred"
    nodes = {n["id"]: n for n in evidence_graph["nodes"]}
    unmapped: List[Dict[str, Any]] = []
    cite = lambda evs: list(dict.fromkeys(e["anchor"] for e in evs))[:6]  # noqa: E731
    name_of = {nid: _camel(n["labels"][0]) for nid, n in nodes.items() if n["kind"] == "concept"}
    related = {r["from"] for r in evidence_graph["relations"]} | {r["to"] for r in evidence_graph["relations"]}
    has_states = set(evidence_graph["states"])
    used = related | has_states | {a["object"] for a in evidence_graph["actions"]} | {r["concept"] for r in evidence_graph["rules"]}
    entities: List[Dict[str, Any]] = []
    relationships: List[Dict[str, Any]] = []
    actions: List[Dict[str, Any]] = []
    rules: List[Dict[str, Any]] = []
    for nid in sorted(n for n in nodes if n.startswith("concept:")):
        n = nodes[nid]
        if nid not in used:
            unmapped.append({"candidate": nid, "why": "named in the text, but nothing relates it to anything: not proposed as an entity",
                             "evidence": cite(n["mentions"])})
            continue
        readings = evidence_graph["states"].get(nid, {}).get("readings", [])
        states = readings[0]["states"] if readings else []
        entities.append({"name": name_of[nid], "description": (n["definitions"] or [f"Read as '{n['labels'][0]}'"])[0][:300],
                         "states": states, "attributes": [],
                         "rationale": f"{', '.join(n['methods'])}; written as {', '.join(repr(l) for l in n['labels'][:4])}",
                         "basis": basis if n["basis"] in ("stated", "derived") else "inferred",
                         "sources": cite(n["mentions"] + [e for r in readings for e in r["evidence"]]), "confidence": 0.5})
    for r in evidence_graph["relations"]:
        if r["type"] == "specialization":
            unmapped.append({"candidate": f"{r['from']} is a kind of {r['to']}", "evidence": cite(r["evidence"]),
                             "why": "the model has no specialisation between entities (interfaces are the nearest construct): left for a person"})
            continue
        a, b = name_of.get(r["from"]), name_of.get(r["to"])
        if not a or not b or a == b:
            unmapped.append({"candidate": f"{r['from']} -> {r['to']}", "why": "an end of the relation is not a concept", "evidence": cite(r["evidence"])})
            continue
        relationships.append({"from": a, "to": b, "type": _snake(r["verb"]), "cardinality": r["cardinality"] or "1..*",
                              "rationale": f"{r['method']} ({r['type']}); stated in the document", "basis": basis, "sources": cite(r["evidence"]),
                              "confidence": 0.5})
    seen_actions = set()
    for act in evidence_graph["actions"]:
        target = name_of.get(act["object"])
        if not target:
            continue
        name = _snake(f"{act['verb']} {nodes[act['object']]['labels'][0]}")
        if name in seen_actions:
            continue
        seen_actions.add(name)
        # a state change is attached only when the text states a transition the verb can be tied to; otherwise none
        actions.append({"name": name, "description": f"{act['verb']} {nodes[act['object']]['labels'][0]}",
                        "capability": f"ops.{name}", "requires": [], "effects": [], "side_effect": "none",
                        "rationale": f"{act['method']}; done by '{nodes[act['role']]['labels'][0] if act['role'] in nodes else act['role']}'",
                        "basis": basis, "sources": cite(act["evidence"]), "confidence": 0.5})
    for t in evidence_graph["transitions"]:
        unmapped.append({"candidate": f"{t['concept']}: {t['from']} -> {t['to']}", "evidence": cite(t["evidence"]),
                         "why": "a transition is read, but no action of the text can be tied to it with certainty: left for a person"
                                + (f" (condition: {t['when']})" if t["when"] else "")})
    for rule in evidence_graph["rules"]:
        unmapped.append({"candidate": f"{rule['rule']} on {rule['concept']}" + (f" by {rule['role']}" if rule["role"] else ""),
                         "evidence": cite(rule["evidence"]), "safety": True,
                         "why": "a rule about approval, access or prohibition is never turned into an enforceable rule by "
                                "extraction: its action, condition and role are for a person to state"
                                + (f" (condition read: '{rule['condition']}')" if rule["condition"] else "")})
    for ref in evidence_graph["references"]:
        unmapped.append({"candidate": f"reference {ref['label']}", "why": "a document reference, not a business concept",
                         "evidence": cite(ref["evidence"])})
    questions = [{"id": f"q{i + 1}", "question": f"{a['key']}: {a['why']}. Which reading is right?", "why": "the text is read two ways"}
                 for i, a in enumerate(evidence_graph["ambiguities"][:20])]
    # the model requires states on every entity; none is invented: the person is asked
    questions += [{"id": f"s{i + 1}", "question": f"Which states does '{e['name']}' go through? The text states none.",
                   "why": "an entity needs at least one state, and a state the text does not give is not made up"}
                  for i, e in enumerate([e for e in entities if not e["states"]][:20])]
    questions += [{"id": f"m{i + 1}", "question": f"Are {' and '.join(m['members'])} the same thing?", "why": m["why"]}
                  for i, m in enumerate([m for m in evidence_graph["merges"] if m["decision"] == "proposed"][:20])]
    roles = [{"name": nodes[n]["labels"][0][:64], "description": "read in the text as someone who acts or decides"}
             for n in sorted(nodes) if n.startswith("role:")]
    answer = {"entities": entities, "relationships": relationships, "actions": actions, "rules": rules, "goals": [],
              "questions": questions, "assumptions": [], "unknowns": [u["why"][:200] for u in unmapped if u.get("safety")][:20],
              "roles": roles[:40], "agents": [], "integrations": [],
              "understanding": {"summary": "Concepts and relations read from the documents by a deterministic extractor; "
                                           "nothing was inferred beyond the sentence patterns it names.",
                                "outcome": "", "actors": [r["name"] for r in roles][:20], "out_of_scope": []}}
    return answer, unmapped


def passages(sources: Sequence[Mapping[str, Any]], answer: Mapping[str, Any], limit: int = 20) -> Tuple[List[Dict[str, str]], List[str]]:
    """The anchors the answer cites, as the passages the proposal contract takes (at most ``limit``: the contract's
    own bound). Anchors cited beyond it are returned apart: an element citing only those will read as unsupported."""
    cited: List[str] = []
    for section in ("entities", "relationships", "actions", "rules", "goals"):
        for item in answer.get(section) or []:
            for ref in item.get("sources") or []:
                if ref not in cited:
                    cited.append(ref)
    text = {a["id"]: a["text"] for s in sources for a in s["anchors"]}
    given = [{"id": ref, "text": text[ref][:8000]} for ref in cited[:limit] if ref in text]
    return given, cited[limit:]


class DocumentExtraction:
    """A gateway provider that returns one fixed answer built from documents. It contacts nothing; it is not a
    language model and is never presented as one."""

    name = "document-extraction"

    def __init__(self, answer: Mapping[str, Any]):
        self.answer = answer

    def capabilities(self) -> Any:
        from .ai import Capabilities
        return Capabilities(self.name, "deterministic sentence patterns over the given documents (no network)", "native",
                            False, False, False, "not a language model: a pattern-based extractor", language_model=False)

    def invoke(self, call: Any) -> Any:
        from .ai import ProviderReply
        return ProviderReply(json.dumps(self.answer), "complete", {}, f"autology.docintel {CONTRACT}")


def propose(sources: Sequence[Mapping[str, Any]], brief: str, document: Optional[Mapping[str, Any]] = None,
            decisions: Optional[Mapping[str, str]] = None, stated_as_supplied: bool = False,
            answer_override: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """The whole path: sources, candidates, evidence graph, answer, then :func:`autology.architect.propose`, which
    validates it like any answer. Returns the proposal with the graph and the unmapped findings beside it."""
    from . import architect
    from .ai import ModelGateway, WorkspaceAI

    evidence_graph = graph(extract(sources), decisions)
    answer, unmapped = to_answer(evidence_graph, stated_as_supplied)
    if answer_override is not None:  # for measurement only: an altered answer, said so by the caller
        answer = dict(answer_override)
    given, beyond = passages(sources, answer)
    gateway = ModelGateway({"document-extraction": DocumentExtraction(answer)},
                           {"documents": WorkspaceAI("document-extraction", f"autology.docintel {CONTRACT}", ("synthetic",))})
    proposal = architect.propose(gateway, "documents", brief[:4000], document, sources=given, data_classes=("synthetic",))
    if beyond:
        unmapped.append({"candidate": f"{len(beyond)} cited paragraph(s)", "evidence": beyond[:10],
                         "why": "the proposal contract takes at most 20 passages: elements citing only these read as unsupported"})
    return {"proposal": proposal, "graph": evidence_graph, "unmapped": unmapped, "passages": [p["id"] for p in given],
            "authoritative": False}
