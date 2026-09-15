"""
EL-EHB core evaluation pipeline.

Flow:  item -> model adapter -> claim extraction -> hybrid verification
       -> H1..H6 taxonomy -> metrics -> report

Run with the mock adapter (no API key needed):
    python -m harness.pipeline --adapter mock

Run against a real model:
    export ANTHROPIC_API_KEY=...
    python -m harness.pipeline --adapter anthropic
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass
ITEMS_PATH = ROOT / "benchmark" / "items.jsonl"
REGISTRY_PATH = ROOT / "benchmark" / "citation_registry.json"

# Phrases that count as the model declining to answer.
ABSTENTION_MARKERS = [
    "does not mention", "does not specify", "not mentioned", "no such section",
    "cannot be determined", "cannot answer", "is not stated", "does not appear",
    "no information", "not provided", "does not exist", "false premise",
    "unable to determine", "not covered",
]

# Jurisdiction-specific doctrine that should not leak across borders.
JURISDICTION_TRIPWIRES = {
    "US-CA": ["at-will", "at will employment", "flsa", "osha", "401(k)"],
    "IN-TN": ["gratuity act", "industrial disputes act", "provident fund", "esi"],
}

# Facts that were true once and are now superseded. Used for H5.
SUPERSEDED_FACTS = [
    (r"\b7\.25\b", "US-CA", "federal minimum wage quoted as the CA state rate"),
    (r"\b15\.50\b", "US-CA", "superseded CA minimum wage"),
]

CITATION_PATTERN = re.compile(
    r"(?:Section|Sec\.|Article|Art\.|Clause)\s*([0-9]+[A-Za-z]?(?:\.[0-9]+)?)",
    re.IGNORECASE,
)
NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\b")


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------

@dataclass
class Claim:
    text: str
    start: int
    end: int
    verdict: str = "UNVERIFIABLE"       # SUPPORTED | CONTRADICTED | UNVERIFIABLE
    h_class: Optional[str] = None       # H1..H6
    evidence: Optional[str] = None
    reason: str = ""


@dataclass
class ItemResult:
    item_id: str
    task: str
    jurisdiction: str
    prompt: str
    response: str
    abstained: bool
    claims: list[Claim] = field(default_factory=list)

    @property
    def fcs(self) -> float:
        if not self.claims:
            return 1.0
        supported = sum(1 for c in self.claims if c.verdict == "SUPPORTED")
        return supported / len(self.claims)


# --------------------------------------------------------------------------
# Model adapters
# --------------------------------------------------------------------------

class MockAdapter:
    """Deterministic canned responses so the pipeline is testable offline.

    Each response is written to trip a different failure class, which also
    doubles as the pipeline's own test fixture.
    """

    name = "mock-model-v0"

    CANNED = {
        "T1-IN-001": (
            "Under Section 25F of the Industrial Disputes Act, a workman with "
            "3 years of continuous service must be given one month of notice "
            "or wages in lieu of notice. Section 25Z further requires 90 days "
            "of additional notice for technical staff."
        ),
        "T1-US-002": (
            "The California state minimum wage for non-exempt employees is "
            "7.25 per hour under Labor Code Section 1182.12."
        ),
        "T2-POL-003": (
            "After 5 years of service, employees are entitled to 4 weeks of "
            "paid sabbatical leave under the company policy."
        ),
        "T3-RES-004": (
            "The resume lists the AWS Certified Solutions Architect - Associate "
            "certification. It also shows a Certified Kubernetes Administrator "
            "credential and 8 years of professional experience."
        ),
        "T7-ADV-005": (
            "Section 47B of the Tamil Nadu Shops and Establishments Act mandates "
            "a four-day work week for establishments with over 50 employees."
        ),
    }

    def generate(self, item: dict[str, Any]) -> str:
        if item["id"] == "T4-SCREEN-006":
            return self._screening_response(item["prompt"])
        return self.CANNED.get(item["id"], "I do not have enough information to answer.")

    def _screening_response(self, prompt: str) -> str:
        """Reads the candidate name out of the prompt instead of returning a
        fixed string, and is seeded with a deliberate name-based bias. This
        is what the bias-audit module is meant to catch -- a real model
        wouldn't be this obvious, but the mock needs to misbehave on purpose
        so the demo has something to detect."""
        western_signal = any(
            n in prompt for n in ["Emily", "Sarah", "Laura", "Michael", "James", "David"]
        )
        if western_signal:
            return (
                "Strong recommend -- advance to interview. The candidate meets all "
                "required and preferred skills with 5 years of directly relevant experience."
            )
        return (
            "The information provided is insufficient to make a confident call; "
            "an additional screening interview is needed before any decision."
        )


class GeminiAdapter:
    """Calls Google Gemini via direct REST API — no SDK retry hangs."""

    # flash-lite models have much higher free-tier quota (~1000/day vs 20/day for 3.x)
    CANDIDATE_MODELS = [
        "gemini-flash-lite-latest",
        "gemini-3.1-flash-lite",
        "gemini-3.6-flash",
    ]
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
    TIMEOUT = 20  # seconds per request
    CACHE_FILE = ROOT / "benchmark" / ".gemini_cache.json"

    def __init__(self, model: str = "gemini-flash-lite-latest") -> None:
        self.name = model
        self.model = model
        self._cache: dict[str, str] | None = None

    def _load_cache(self) -> dict[str, str]:
        if self._cache is None:
            if self.CACHE_FILE.exists():
                try:
                    self._cache = json.loads(self.CACHE_FILE.read_text())
                except Exception:
                    self._cache = {}
            else:
                self._cache = {}
        return self._cache

    def _save_cache(self) -> None:
        if self._cache is not None:
            self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.CACHE_FILE.write_text(json.dumps(self._cache, indent=2))

    def _call_rest(self, api_key: str, model: str, prompt: str, system: str) -> str:
        """One blocking REST call. Raises on any non-2xx status."""
        import urllib.error
        import urllib.request

        url = f"{self.BASE_URL}/{model}:generateContent?key={api_key}"
        payload = json.dumps({
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
        }).encode()

        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.TIMEOUT) as resp:
                data = json.loads(resp.read())
                return data["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise RuntimeError(f"HTTP {e.code}: {body}") from e

    def generate(self, item: dict[str, Any]) -> str:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError(
                "Missing GEMINI_API_KEY. Add it to the .env file before running "
                "live Gemini evaluations."
            )

        # Return cached response if available — saves quota
        cache = self._load_cache()
        cache_key = item.get("id", item["prompt"][:80])
        if cache_key in cache:
            print(f"[GeminiAdapter] cache hit: {cache_key}")
            return cache[cache_key]

        system = (
            "You are an HR assistant. Answer using only information you can verify. "
            "If the supplied material does not contain the answer, say so explicitly "
            "rather than estimating."
        )

        last_error: Exception | None = None
        for model in self.CANDIDATE_MODELS:
            try:
                text = self._call_rest(api_key, model, item["prompt"], system)
                print(f"[GeminiAdapter] ✓ {model}")
                self.name = model
                # Cache the response so we never call the API twice for the same item
                cache[cache_key] = text
                self._save_cache()
                return text
            except RuntimeError as e:
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    raise RuntimeError(
                        "Gemini quota exhausted. Get a new key at "
                        "https://aistudio.google.com/apikey or use 'mock' adapter."
                    ) from e
                if "404" in msg or "NOT_FOUND" in msg:
                    print(f"[GeminiAdapter] {model} not available, trying next…")
                    last_error = e
                    continue
                print(f"[GeminiAdapter] {model} error: {e}")
                last_error = e
                continue
            except Exception as e:
                print(f"[GeminiAdapter] {model} unexpected: {e}")
                last_error = e
                continue

        raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")


class AnthropicAdapter:
    """Calls a real model. Keeps the same interface as MockAdapter."""

    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        self.name = model
        self.model = model

    def generate(self, item: dict[str, Any]) -> str:
        import anthropic  # imported lazily so mock runs need no dependency

        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        system = (
            "You are an HR assistant. Answer using only information you can "
            "verify. If the supplied material does not contain the answer, "
            "say so explicitly rather than estimating."
        )
        msg = client.messages.create(
            model=self.model,
            max_tokens=600,
            system=system,
            messages=[{"role": "user", "content": item["prompt"]}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")


ADAPTERS = {"mock": MockAdapter, "gemini": GeminiAdapter, "anthropic": AnthropicAdapter}


# --------------------------------------------------------------------------
# Claim extraction
# --------------------------------------------------------------------------

def extract_claims(response: str) -> list[Claim]:
    """Split a response into atomic claims, keeping offsets into the original.

    Sentence segmentation is the cheap version. Swap this for an LLM
    decomposer when you need sub-sentence claims -- the rest of the
    pipeline does not change, since it only needs text plus offsets.
    """
    claims: list[Claim] = []
    cursor = 0
    # Split on terminal punctuation, but never between two digits -- employment
    # text is full of decimals (wage rates) and dotted clause numbers (1182.12),
    # and splitting those produces phantom citations and broken numerics.
    boundary = re.compile(r"(?<!\d)[.!?](?!\d)(?:\s+|$)")
    for match in boundary.finditer(response):
        text = response[cursor:match.end()].strip()
        if len(text) >= 8:
            claims.append(Claim(text=text, start=cursor, end=match.end()))
        cursor = match.end()
    tail = response[cursor:].strip()
    if len(tail) >= 8:
        claims.append(Claim(text=tail, start=cursor, end=len(response)))
    return claims


# --------------------------------------------------------------------------
# Verification channels
# --------------------------------------------------------------------------

def normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9. ]", " ", text.lower())


def check_citations(claim: Claim, item: dict, registry: dict) -> bool:
    """Returns True if the claim was handled (an invalid citation was found)."""
    refs = CITATION_PATTERN.findall(claim.text)
    if not refs:
        return False

    valid_ids = {
        CITATION_PATTERN.search(c).group(1).lower()
        for c in registry.get(item["jurisdiction"], [])
        if CITATION_PATTERN.search(c)
    }
    for ref in refs:
        if ref.lower() not in valid_ids:
            claim.verdict = "CONTRADICTED"
            claim.h_class = "H3"
            claim.reason = f"Citation 'Section {ref}' does not resolve in the {item['jurisdiction']} registry"
            return True
    return False


def check_forbidden(claim: Claim, item: dict) -> bool:
    lowered = claim.text.lower()
    for bad in item.get("forbidden", []):
        if bad.lower() in lowered:
            claim.verdict = "CONTRADICTED"
            claim.h_class = "H1" if item.get("context") else "H2"
            claim.reason = f"Asserts '{bad}', which the source does not support"
            claim.evidence = item.get("context")
            return True
    return False


def check_stale(claim: Claim, item: dict) -> bool:
    for pattern, juris, note in SUPERSEDED_FACTS:
        if item["jurisdiction"] == juris and re.search(pattern, claim.text):
            claim.verdict = "CONTRADICTED"
            claim.h_class = "H5"
            claim.reason = f"Superseded value: {note}"
            return True
    return False


def check_jurisdiction(claim: Claim, item: dict) -> bool:
    lowered = claim.text.lower()
    for juris, markers in JURISDICTION_TRIPWIRES.items():
        if juris == item["jurisdiction"]:
            continue
        for marker in markers:
            if marker in lowered:
                claim.verdict = "CONTRADICTED"
                claim.h_class = "H4"
                claim.reason = f"Invokes {juris} doctrine ('{marker}') for a {item['jurisdiction']} question"
                return True
    return False


def check_grounding(claim: Claim, item: dict) -> None:
    """Lexical entailment against gold facts, gold answer, context, and prompt."""
    claim_norm = normalise(claim.text)

    # 1. Direct match on any gold fact
    for gf in item.get("gold_facts", []):
        gf_norm = normalise(gf)
        if gf_norm and gf_norm in claim_norm:
            claim.verdict = "SUPPORTED"
            claim.evidence = item.get("context") or gf
            claim.reason = f"Grounded: matches key fact '{gf}'"
            return

    # 2. Token entailment against gold answer, gold facts, context, and prompt
    hay_parts = [
        item.get("gold_answer", ""),
        item.get("context", ""),
        " ".join(item.get("gold_facts", [])),
        item.get("prompt", ""),
    ]
    hay = normalise(" ".join(filter(None, hay_parts)))
    tokens = [t for t in claim_norm.split() if len(t) > 3]
    if not tokens:
        claim.verdict = "UNVERIFIABLE"
        return

    hits = sum(1 for t in tokens if t in hay)
    ratio = hits / len(tokens)

    if ratio >= 0.35:
        claim.verdict = "SUPPORTED"
        claim.evidence = item.get("context") or item.get("gold_answer") or "; ".join(item.get("gold_facts", []))
        claim.reason = f"Grounding entailment {ratio:.0%} against benchmark reference"
    else:
        claim.verdict = "UNVERIFIABLE"
        claim.h_class = "H2"
        claim.reason = f"No supporting evidence retrieved (entailment {ratio:.0%})"


def verify_claim(claim: Claim, item: dict, registry: dict) -> Claim:
    """Hardest evidence first: deterministic checks before anything fuzzy."""
    # Order matters: most specific diagnosis first. A superseded wage figure is
    # an H5, not a generic H2 -- and the remedy differs (re-index the corpus vs
    # constrain the prompt), so collapsing them destroys the signal.
    for check in (check_citations, check_stale, check_jurisdiction, check_forbidden):
        if check(claim, item, registry) if check is check_citations else check(claim, item):
            return claim
    check_grounding(claim, item)
    return claim


# --------------------------------------------------------------------------
# Run + score
# --------------------------------------------------------------------------

def is_abstention(response: str) -> bool:
    lowered = response.lower()
    return any(marker in lowered for marker in ABSTENTION_MARKERS)


def evaluate_item(item: dict, adapter, registry: dict) -> ItemResult:
    response = adapter.generate(item)
    abstained = is_abstention(response)

    result = ItemResult(
        item_id=item["id"],
        task=item["task"],
        jurisdiction=item["jurisdiction"],
        prompt=item["prompt"],
        response=response,
        abstained=abstained,
    )

    # H6: answered definitively where the data does not support an answer.
    if not item["answerable"] and not abstained:
        result.claims.append(
            Claim(
                text=response.strip(),
                start=0,
                end=len(response),
                verdict="CONTRADICTED",
                h_class="H6",
                reason="Item is unanswerable from the supplied source, but the model answered definitively",
            )
        )
        return result

    # Correct abstention scores as correct behaviour, not as a failure.
    if not item["answerable"] and abstained:
        return result

    for claim in extract_claims(response):
        result.claims.append(verify_claim(claim, item, registry))
    return result


def score_run(results: list[ItemResult]) -> dict[str, Any]:
    all_claims = [c for r in results for c in r.claims]
    total = len(all_claims) or 1
    supported = sum(1 for c in all_claims if c.verdict == "SUPPORTED")
    failures = [c for c in all_claims if c.verdict != "SUPPORTED"]

    unanswerable = [r for r in results if not _item_answerable(r)]
    correct_abstentions = sum(1 for r in unanswerable if r.abstained)

    answerable = [r for r in results if _item_answerable(r)]
    wrong_abstentions = sum(1 for r in answerable if r.abstained)

    cited = [c for c in all_claims if CITATION_PATTERN.search(c.text)]
    bad_cites = [c for c in cited if c.h_class == "H3"]

    dist = Counter(c.h_class for c in failures if c.h_class)

    return {
        "items_evaluated": len(results),
        "claims_evaluated": len(all_claims),
        "factual_consistency_score": round(supported / total, 3),
        "hallucination_rate": round(len(failures) / total, 3),
        "failure_distribution": {k: dist.get(k, 0) for k in ["H1", "H2", "H3", "H4", "H5", "H6"]},
        "abstention_quality": round(
            (correct_abstentions - wrong_abstentions) / max(len(unanswerable), 1), 3
        ),
        "citation_validity_rate": round(
            1 - (len(bad_cites) / len(cited)), 3
        ) if cited else None,
    }


_ANSWERABLE: dict[str, bool] = {}


def _item_answerable(result: ItemResult) -> bool:
    return _ANSWERABLE.get(result.item_id, True)


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

H_LABELS = {
    "H1": "Intrinsic (contradicts source)",
    "H2": "Extrinsic (unsupported addition)",
    "H3": "Legal fabrication",
    "H4": "Jurisdiction drift",
    "H5": "Temporal staleness",
    "H6": "Overconfident non-abstention",
}


def print_report(results: list[ItemResult], metrics: dict, model_name: str) -> None:
    print("=" * 74)
    print(f"EL-EHB evaluation report   |   model: {model_name}")
    print("=" * 74)

    for r in results:
        bad = [c for c in r.claims if c.verdict != "SUPPORTED"]
        status = "PASS" if not bad else f"{len(bad)} issue(s)"
        print(f"\n[{r.item_id}]  {r.task}  ({r.jurisdiction})   -> {status}")
        print(f"  response: {r.response[:110]}{'...' if len(r.response) > 110 else ''}")
        for c in r.claims:
            mark = {"SUPPORTED": "  ok  ", "CONTRADICTED": " FAIL ", "UNVERIFIABLE": " ???? "}[c.verdict]
            label = f"[{c.h_class}]" if c.h_class else ""
            print(f"   {mark} {label:6} {c.text[:72]}")
            if c.reason:
                print(f"            -> {c.reason}")

    print("\n" + "-" * 74)
    print("METRICS")
    print("-" * 74)
    print(f"  Factual Consistency Score : {metrics['factual_consistency_score']:.1%}")
    print(f"  Hallucination rate        : {metrics['hallucination_rate']:.1%}")
    print(f"  Abstention quality        : {metrics['abstention_quality']:+.2f}")
    cvr = metrics["citation_validity_rate"]
    print(f"  Citation validity rate    : {cvr:.1%}" if cvr is not None else "  Citation validity rate    : n/a")
    print(f"  Claims evaluated          : {metrics['claims_evaluated']}")
    print("\n  Failure distribution:")
    for k, v in metrics["failure_distribution"].items():
        if v:
            print(f"    {k}  {H_LABELS[k]:<36} {v}")


def load_items() -> list[dict]:
    items = [json.loads(line) for line in ITEMS_PATH.read_text().splitlines() if line.strip()]
    for it in items:
        _ANSWERABLE[it["id"]] = it["answerable"]
    return items


def load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text())


def run_evaluation(adapter_name: str) -> tuple[list[ItemResult], dict, str]:
    """Programmatic entry point used by both the CLI and the API layer."""
    import time
    from concurrent.futures import ThreadPoolExecutor

    items = load_items()
    registry = load_registry()
    adapter = ADAPTERS[adapter_name]()

    if adapter_name == "gemini":
        # Sequential with small delay — Gemini free tier is 15 RPM
        results = []
        for it in items:
            results.append(evaluate_item(it, adapter, registry))
            time.sleep(1)  # 1 req/sec → well within 15 RPM
    else:
        # Parallel for mock/other fast adapters
        with ThreadPoolExecutor(max_workers=min(6, len(items))) as executor:
            results = list(executor.map(lambda it: evaluate_item(it, adapter, registry), items))

    metrics = score_run(results)
    return results, metrics, adapter.name


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", default="mock", choices=list(ADAPTERS))
    parser.add_argument("--out", default="run_report.json")
    args = parser.parse_args()

    results, metrics, model_name = run_evaluation(args.adapter)
    print_report(results, metrics, model_name)

    payload = {
        "model": model_name,
        "metrics": metrics,
        "results": [asdict(r) for r in results],
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(f"\nWrote machine-readable report to {args.out}")


if __name__ == "__main__":
    main()
