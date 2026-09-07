"""
Cast Profiler — character gender/age/voice hints for blind casting.

A listener casting a book BEFORE reading it can't know whether "Astryx" is
feminine or masculine — and a wrong-gender voice is the most expensive
casting mistake (discovered after rendering, fixed by re-rendering every
line the character speaks). This pass infers, per speaking character:

    gender:      feminine | masculine | ambiguous
    age:         child | young-adult | adult | elder | unknown
    voice_hints: 2-4 free words for the caster ("gravelly, weary")
    evidence:    short quote grounding the call

Two layers, cheap first:
  1. Deterministic — gendered titles in the NAME itself (Abbess, Brother,
     Lady, Mr...) resolve instantly, no LLM, confidence 0.9.
  2. LLM — for the rest, the model reads a few of the character's lines
     WITH surrounding narration (where the he/she/they pronouns live) and
     returns a profile. Threshold-gated; below it → ambiguous/unknown.

Profiles land in ir["character_profiles"] = {name: {...}} — additive, never
touches attribution fields. The cast screen renders them as chips.

Ollama endpoint: PROSECAST_OLLAMA_URL (shared with the other passes).
"""

import json
import re
import urllib.request
import urllib.error
from typing import Callable, Optional

from prosecast import library as lib

from prosecast.llm_attributor import OLLAMA_BASE

OLLAMA_API = f"{OLLAMA_BASE}/api/generate"

MIN_LINES_TO_PROFILE = 2      # walk-ons aren't worth a call (or a chip)
SAMPLE_LINES = 4              # excerpts per character shown to the model
CONTEXT_CHARS = 260           # narration context per excerpt side
VALID_GENDERS = {"feminine", "masculine", "ambiguous"}
VALID_AGES = {"child", "young-adult", "adult", "elder", "unknown"}

# Layer 1: gendered titles/honorifics inside the character's own name.
FEMININE_TITLES = {
    "mrs", "ms", "miss", "lady", "dame", "queen", "princess", "duchess",
    "abbess", "sister", "mother", "aunt", "auntie", "madam", "madame",
    "mistress", "widow", "countess", "baroness", "empress",
}
MASCULINE_TITLES = {
    "mr", "sir", "lord", "king", "prince", "duke", "abbot", "brother",
    "father", "uncle", "master", "count", "baron", "emperor", "monk",
}

# ── Layer 1b: common English given names ─────────────────────────────────────
#
# What this is for: on rung 1 there is no Ollama, so the LLM layer never runs
# and EVERY character comes out unprofiled — which is how the first Windows
# render gave Elizabeth and Jane male voices. A list of names is enough to fix
# the common case without asking anyone to install anything.
#
# What it is not: a way to know someone's gender. It is a frequency table for
# English-language fiction, and it is wrong about real people constantly —
# names move between genders across decades and countries (Evelyn, Hilary and
# Beverly were all men's names within living memory), and it knows nothing
# about names from most of the world. So:
#
#   * It is the LAST resort. A title in the name wins, the LLM reading actual
#     pronouns wins, and a person's own casting always wins.
#   * When in doubt, LEAVE IT OUT. An omission costs a round-robin voice, which
#     is what happens today; a wrong entry costs a re-render of every line the
#     character speaks. AMBIGUOUS_NAMES exists to make that refusal explicit
#     and to stop anyone "helpfully" adding Jordan to a list later.
#   * Confidence is 0.6 — deliberately below what a title or a pronoun earns.
#
# Surnames are absent on purpose: "Darcy" and "Bennet" are how a book names
# people too, and guessing from them is how you cast a butler as a duchess.

FEMININE_NAMES = frozenset("""
abigail ada adelaide adele agatha agnes aileen alice alicia alison amanda
amelia amy anastasia andrea angela anita ann anna annabel anne annette annie
antonia april arabella audrey aurora ava barbara beatrice belinda bella
bernadette bertha bess bessie beth bethany betsy betty blanche brenda bridget
camilla candace carla carmen carol caroline carolyn catherine cathy cecilia
celia charlotte chloe christina christine cindy claire clara clarissa claudia
colette connie constance cora cordelia cornelia crystal cynthia daisy daphne
darlene dawn deborah debra deirdre delia denise diana diane dolores donna dora
doreen doris dorothea dorothy edith edna eileen elaine eleanor elena eliza
elizabeth ella ellen eloise elsie emily emma enid erica erin esme estelle
esther ethel eugenia eunice eva evelyn faith fanny felicity fiona flora
florence frances freda gabriella gail genevieve georgia georgina geraldine
gertrude gillian gina ginny gladys gloria grace greta gretchen gwendolyn
hannah harriet hazel helen helena henrietta hilda holly hope ida imogen ingrid
irene iris isabel isabella isadora ivy jacqueline jane janet janice jasmine
jemima jenna jennifer jenny jessica jill joan joanna joanne jocelyn josephine
joy joyce judith judy julia julie juliet june karen kate katherine kathleen
kathryn kathy katie kay kirsten kitty laura laurel lauren lavinia leah leonora
lettie lila lilian lillian lily linda lisa lois lola lorna lottie louisa
louise lucia lucille lucinda lucy lydia mabel madeleine madeline madge maggie
maisie marcia margaret margery maria marian marianne marie marigold marilyn
marjorie martha mary matilda maud maude maureen mavis maxine meg megan melanie
melissa mercy mildred millicent millie minerva minnie miranda miriam moira
molly mona monica muriel myra myrtle nadia nancy naomi natalie nell nellie
nicola nicole nina nora norah norma octavia olga olive olivia opal ophelia
pamela patience patricia patsy paula pauline pearl peggy penelope penny
persephone phoebe phyllis polly portia priscilla prudence rachel ramona
rebecca regina renee rhoda rhonda rita roberta rosa rosalind rose rosemary
rosie rowena roxanne ruby ruth sabrina sally samantha sandra sarah selina
serena sheila shirley sibyl sonia sophia sophie stella stephanie susan susanna
susannah suzanne sybil sylvia tabitha tamara teresa tessa thelma theodora
theresa tilly tina trudy ursula valerie vanessa vera verity veronica victoria
violet virginia vivienne wanda wendy wilhelmina willa wilma winifred yvonne
zelda zoe
""".split())

MASCULINE_NAMES = frozenset("""
aaron abel abraham adam adrian alan albert alec alexander alfred algernon
allan alvin ambrose andrew angus anthony archibald archie arnold arthur august
augustus austin barnaby barney barry bartholomew basil benedict benjamin
bennett bernard bert bertram bill billy bob boris brandon brendan brian bruce
bruno bryan byron caleb calvin carl cecil cedric charles chester christian
christopher clarence claude clement clifford clive clyde colin conrad
cornelius craig cuthbert cyril cyrus daniel darren dave david dean dennis
derek desmond dick dominic donald douglas duncan dwight earl eddie edgar
edmund edward edwin elias elijah elliot elmer emmanuel enoch eric ernest ethan
eugene eustace everett ezra felix ferdinand fergus floyd francis frank
franklin fraser fred frederick gabriel gareth garrett gavin geoffrey george
gerald gerard gilbert giles glenn godfrey gordon graham grant gregory gustav
guy hamish hank harold harry harvey hector henry herbert herman hiram horace
howard hubert hugh hugo humphrey ian ignatius irving isaac ivan jack jacob
james jared jason jasper jeffrey jeremy jerome jerry jim jimmy joel john
johnny jonah jonathan joseph joshua josiah julian julius justin keith kenneth
kevin lambert lancelot larry laurence lawrence leo leonard leopold lester
lewis liam lionel lloyd louis lucas luke luther malcolm marcus mark martin
marvin matthew maurice max maxwell michael miles milton mitchell montgomery
mortimer moses murray nathan nathaniel neil nelson nicholas nigel noah norman
oliver oscar oswald otto owen patrick paul percival percy perry peter philip
phillip pierce quentin ralph randolph raymond reginald rex richard robert
roderick rodney roger roland ronald rory ross roy rufus rupert russell samuel
saul sebastian seth seymour silas simon solomon stanley stephen steven stewart
stuart sylvester theodore thomas timothy tobias toby todd tom tommy tony
travis trevor tristan ulysses vernon victor vincent virgil wallace walter
warren wayne wesley wilbur wilfred william willie winston zachary
""".split())

# Names this table refuses to answer for, so that a later "helpful" addition
# has to argue with a list rather than slip in. Genuinely unisex in English,
# or common enough in both columns that a coin flip is not worth a re-render.
AMBIGUOUS_NAMES = frozenset("""
alex ali angel ashley aubrey avery bailey billie blair blake brett brook
brooke cameron carey carroll casey cassidy charlie chris corey courtney dakota
dale dana darcy devon drew dylan eden ellis emerson finley gale harper hayden
hilary hollis jackie jamie jean jesse jo jody jordan kelly kendall kim kirby
lee leslie lindsay logan lynn marion meredith morgan nicky noel parker pat
payton quinn reagan reese regan riley robin rowan ryan sage sam sandy sasha
shannon shawn shelby sidney skyler spencer stacy sterling sydney taylor terry
tracy val vivian
""".split())

PROMPT_TEMPLATE = """\
You are helping cast voice actors for an audiobook. Based ONLY on the
excerpts below, profile the character "{name}". Surrounding narration is
included — pronouns and descriptions there are your main evidence.

EXCERPTS:
{excerpts}

Reply with ONLY one line of valid JSON — no explanation, no markdown:
{{"gender": "feminine|masculine|ambiguous", "age": "child|young-adult|adult|elder|unknown", "voice_hints": "2-4 words", "confidence": 0.0, "evidence": "short quote from the excerpts"}}

Rules:
- gender is how the text refers to them (he/she/they, descriptions). If the
  excerpts never indicate it, use "ambiguous" with low confidence — do NOT
  guess from the name alone.
- confidence 0.0-1.0 reflects the pronoun/description evidence, not intuition.
- evidence: the strongest phrase you saw (e.g. "she snorted", "the old man").
"""


# ── Layer 1: deterministic ────────────────────────────────────────────────────

def profile_from_name(name: str) -> Optional[dict]:
    """Gendered title inside the name itself → instant profile (no LLM)."""
    tokens = set(re.findall(r"[a-z]+", name.lower()))
    fem = bool(tokens & FEMININE_TITLES)
    masc = bool(tokens & MASCULINE_TITLES)
    if fem == masc:          # neither, or contradictory
        return None
    title = (tokens & (FEMININE_TITLES | MASCULINE_TITLES)).pop()
    return {
        "gender": "feminine" if fem else "masculine",
        "age": "unknown",
        "voice_hints": "",
        "confidence": 0.9,
        "evidence": f"title '{title}' in name",
        "method": "title",
    }


def profile_from_first_name(name: str) -> Optional[dict]:
    """A common English given name in the character's name → a guess.

    Every token is checked, not just the first, so "Old Tom" and "Aunt Sally"
    resolve. Tokens the table refuses to answer for are skipped rather than
    treated as evidence, and a name whose tokens disagree ("Jack and Jill")
    resolves to nothing at all. Read the comment above FEMININE_NAMES before
    trusting this for anything: it is a frequency table, not knowledge.
    """
    votes = set()
    for token in re.findall(r"[a-z]+", name.lower()):
        if token in AMBIGUOUS_NAMES:
            continue
        if token in FEMININE_NAMES:
            votes.add("feminine")
        elif token in MASCULINE_NAMES:
            votes.add("masculine")
    if len(votes) != 1:
        return None
    gender = votes.pop()
    return {
        "gender": gender,
        "age": "unknown",
        "voice_hints": "",
        "confidence": 0.6,          # below a title (0.9) and below a pronoun
        "evidence": f"'{name}' is a common {gender} given name in English",
        "method": "first-name",
    }


def guess_profile(name: str) -> Optional[dict]:
    """Everything the rules can tell about a character without an LLM.

    This is the whole cast profiler on rung 1 — no Ollama, no AI pass, just a
    title in the name or a name the table knows. Returns None when it has
    nothing, which is not a failure: a character with no profile is cast by
    round-robin exactly as before.
    """
    return profile_from_name(name) or profile_from_first_name(name)


# ── Excerpt gathering ─────────────────────────────────────────────────────────

def gather_excerpts(ir_data: dict, name: str, limit: int = SAMPLE_LINES) -> list:
    """Spread samples across the book — pronoun evidence clusters by scene,
    and early scenes may deliberately obscure a character."""
    hits = []
    for chapter in ir_data.get("chapters", []):
        for b in chapter.get("blocks", []):
            if (b.get("type") == "dialogue" and b.get("speaker") == name
                    and not b.get("unresolved")):
                hits.append(b)
    if not hits:
        return []
    step = max(1, len(hits) // limit)
    picked = hits[::step][:limit]
    out = []
    for b in picked:
        before = (b.get("context_before") or "")[-CONTEXT_CHARS:]
        after = (b.get("context_after") or "")[:CONTEXT_CHARS]
        out.append(f"...{before}\n  {name}: {b.get('text', '')}\n{after}...")
    return out


# ── LLM layer ─────────────────────────────────────────────────────────────────

def _call_ollama(prompt: str, model: str, timeout: int = 120) -> Optional[str]:
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 160},
    }).encode()
    req = urllib.request.Request(
        OLLAMA_API, data=payload, headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()).get("response", "")
    except urllib.error.URLError as e:
        print(f"  [PROFILE] Connection error: {e}")
        return None
    except Exception as e:
        print(f"  [PROFILE] Error: {e}")
        return None


def parse_profile_response(raw: str) -> Optional[dict]:
    """Tolerates <think> blocks and fences; validates enums; clamps confidence."""
    if not raw:
        return None
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    text = re.sub(r"```(?:json)?", "", text).strip()
    start = text.find("{")
    if start < 0:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    gender = str(data.get("gender", "")).strip().lower()
    if gender not in VALID_GENDERS:
        gender = "ambiguous"
    age = str(data.get("age", "")).strip().lower()
    if age not in VALID_AGES:
        age = "unknown"
    try:
        conf = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
    except (TypeError, ValueError):
        conf = 0.0
    return {
        "gender": gender,
        "age": age,
        "voice_hints": str(data.get("voice_hints", ""))[:60],
        "confidence": round(conf, 2),
        "evidence": str(data.get("evidence", ""))[:160],
        "method": "llm",
    }


# ── Main pass ─────────────────────────────────────────────────────────────────

def run_profile_pass(
    ir_data: dict,
    model: str = "llama3.2",
    confidence_threshold: float = 0.5,
    reprofile: bool = False,
    checkpoint_path: Optional[str] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    report: Optional[dict] = None,
) -> dict:
    """Profile every character with >= MIN_LINES_TO_PROFILE dialogue blocks.

    Existing profiles are kept unless reprofile=True (so re-runs after new
    corrections only fill gaps). Below-threshold LLM answers are stored as
    ambiguous/unknown — an honest '?' chip beats a confident wrong one.
    """
    def _fill(**kw):
        if report is not None:
            report.update(kw)

    _fill(profiled=0, targets=0, errors=0, aborted=False, abort_reason=None)

    counts = {}
    for ch in ir_data.get("chapters", []):
        for b in ch.get("blocks", []):
            if b.get("type") == "dialogue" and not b.get("unresolved"):
                s = b.get("speaker")
                if s and s not in ("NARRATOR", "UNKNOWN"):
                    counts[s] = counts.get(s, 0) + 1

    targets = [n for n, c in sorted(counts.items(), key=lambda x: -x[1])
               if c >= MIN_LINES_TO_PROFILE]
    profiles = ir_data.setdefault("character_profiles", {})
    if not reprofile:
        targets = [n for n in targets if n not in profiles]

    _fill(targets=len(targets))
    if not targets:
        print("[PROFILE] Every eligible character already profiled — nothing to do.")
        if on_progress:
            on_progress(0, 0)
        return ir_data

    print(f"[PROFILE] Model:   {model}")
    print(f"[PROFILE] Targets: {len(targets)} characters (>= {MIN_LINES_TO_PROFILE} lines)")

    by_title = llm_done = ambiguous = errors = by_name = 0
    consecutive_errors = 0
    done = 0
    if on_progress:
        on_progress(0, len(targets))

    def _step(who: str) -> None:
        nonlocal done
        done += 1
        if on_progress:
            on_progress(done, len(targets))

    def _fallback(who: str) -> None:
        """The name table, for a character the LLM could not read — because
        Ollama went away, because it answered nonsense, or because there was
        nothing to show it. Better than leaving the character unprofiled."""
        nonlocal by_name
        guessed = profile_from_first_name(who)
        if guessed:
            profiles[who] = guessed
            by_name += 1
            print(f"  ~ {who:<22} {guessed['gender']:<10} (common given name)")

    for name in targets:
        titled = profile_from_name(name)
        if titled:
            profiles[name] = titled
            by_title += 1
            print(f"  ✓ {name:<22} {titled['gender']:<10} (title, no LLM)")
            _step(name)
            continue

        excerpts = gather_excerpts(ir_data, name)
        if not excerpts:
            _fallback(name)
            _step(name)
            continue
        raw = _call_ollama(
            PROMPT_TEMPLATE.format(name=name, excerpts="\n\n".join(excerpts)),
            model,
        )
        if raw is None:
            errors += 1
            _fallback(name)
            consecutive_errors += 1
            if consecutive_errors >= 3:
                print(f"\n[PROFILE] {consecutive_errors} connection failures in a row — "
                      "aborting pass (profiles so far are saved; re-run to resume).")
                _fill(aborted=True,
                      abort_reason=f"Ollama stopped answering after {consecutive_errors} "
                                   "tries while profiling the cast — the profiles finished "
                                   "so far are saved.")
                break
            _step(name)
            continue
        consecutive_errors = 0
        prof = parse_profile_response(raw)
        if prof is None:
            errors += 1
            _fallback(name)
            _step(name)
            continue
        if prof["confidence"] < confidence_threshold:
            # The model read the pronouns and found nothing. A common given
            # name is weak evidence, but it beats casting by round-robin.
            guessed = profile_from_first_name(name)
            if guessed:
                prof = guessed
                by_name += 1
            else:
                prof["gender"] = "ambiguous"
                ambiguous += 1
        else:
            llm_done += 1
        profiles[name] = prof
        print(f"  ✓ {name:<22} {prof['gender']:<10} conf={prof['confidence']:.2f}  "
              f"{prof['evidence'][:45]!r}")

        if checkpoint_path:
            lib.write_json_atomic(checkpoint_path, ir_data)
        _step(name)

    print(f"\n[PROFILE] {by_title} by title, {llm_done} by LLM, "
          f"{by_name} by name, {ambiguous} ambiguous, {errors} errors")
    _fill(profiled=by_title + llm_done + by_name + ambiguous, errors=errors)
    return ir_data
