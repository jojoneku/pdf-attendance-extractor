"""
Sex / gender inference for Filipino (Visayan / Bohol) given names.

Public API
----------
    infer_sex(first_name, middle_name="", full_given="", suffix="", lexicon=None)
        -> (sex, confidence, reason)

``sex`` is "M", "F" or "" (undetermined, confidence < MIN_CONFIDENCE).

How it works (layered, naive-Bayes style log-odds)
--------------------------------------------------
1. Normalise: uppercase, strip accents/punctuation, split into tokens, drop
   initials and generational suffixes (JR., SR., II, III ...).  The Filipino
   abbreviation "MA." (= Maria) is treated as a strong female prefix.
2. Lexicon: ``data/given_name_gender.json`` holds aggregated given-name
   counts {name: [male_count, female_count]} derived from a labelled local
   corpus (no surnames, no personal records).  Two tables are kept: "first"
   (token seen as the first given name) and "later" (token seen after the first
   one, e.g. KYLA *JADE*, JOHN *PAUL*).  Each token gives a smoothed log-odds;
   later tokens are down-weighted by position.
3. Curated overrides: priors for very common Filipino names the corpus may lack
   or get wrong (JHON, JUN, REY ... -> M; JOY, MAE, ANN ... -> F) and a
   "unisex" list whose single-token evidence is capped so it cannot decide
   alone with high confidence.
4. Morphology: for unseen / rare first names a low-confidence prior from word
   endings (-lyn, -elle, -ette, -a ... -> F; -ito, -ard, -mar ... -> M).
5. Return "" when confidence < 0.6.  A suffix (JR./SR./III) adds strong male
   evidence, but a clearly female name still wins (the corpus contains women
   whose names end in "JR." or "II").

CLI:  python -m backend.gender "FIRST" ["MIDDLE"] [--given "FULL GIVEN"] [--suffix JR.]
prints ``sex,confidence,reason``.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

MIN_CONFIDENCE = 0.6

LEXICON_PATH = Path(__file__).resolve().parent / "data" / "given_name_gender.json"

# --- tunable parameters (tuned by cross-validation, see gender_train.py) ---
POS_WEIGHTS = (1.0, 1.0, 0.6, 0.3)  # weight of token at position 0,1,2,3+
CROSS_TABLE = 0.5  # weight of the "other position" table's counts
ALPHA = 0.6  # additive smoothing of counts
SUFFIX_LO = {"JR": 3.2, "SR": 3.2, "III": 3.0, "IV": 3.0, "II": 0.4}
MA_LO = 4.5  # "MA." / "MARIA" prefix => female
TEMPERATURE = 1.0  # >1 softens confidence
MID_WEIGHT = 0.0  # weight of middle-name tokens (they are usually surnames)

SUFFIXES = {"JR", "SR", "II", "III", "IV", "JNR", "SNR"}
MARIA_PREFIXES = {"MA", "MARIA"}

# ---------------------------------------------------------------------------
# Curated knowledge
# ---------------------------------------------------------------------------
# Strong priors (log-odds added to the corpus evidence).  Positive => male.
_M_NAMES = """
JHON JHUN JUN JUNJUN JUNIOR REY RHEY REYNALDO RENE ROBERT RODEL RODEN ROLAND
ROMEO ROMMEL RONALD RONIE RONNIE ROGELIO ROLANDO ROMAR RENATO RICARDO RICHARD
RAMON RAFAEL RAYMUND RAYMOND REX RIZALDY RODOLFO RUEL RUFINO RUBEN
JOHN JAMES JOSE JOSEPH JOSHUA JUAN JOEL JOMAR JOMEL JOHNREY JOHNLOYD JERICO JEROME
JEFFREY JEFF JERRY JESUS JIMMY JONATHAN JOHNNY JAYSON JASON JAYVEE JAYMAR JAYR
MARK MARC MARCO MARVIN MARLON MARIO MICHAEL MIGUEL MARLO
PAUL PEDRO PATRICK PHILIP PHILLIP PRINCE
KENNETH KENT KEVIN KURT KYLE KARL CARL CARLO CARLOS CHARLES CHRISTIAN CHRISTOPHER CHESTER
DANIEL DAVID DAVE DENNIS DEXTER DANILO DOMINIC DARWIN DALE
ERNEST ERNESTO EDGAR EDWARD EDUARDO EDMUND ELMER ERIC ERICK EARL ENRICO ERWIN EMMANUEL
FRANCIS FRANCO FERDINAND FERNANDO FELIX FELIPE FREDERICK
GABRIEL GEORGE GERALD GILBERT GLENN GREGORY GERARDO
HARVEY HENRY HERBERT
IAN IVAN ISAAC
LEO LEONARD LEONARDO LORENZO LUIS LUCAS LUKE LAWRENCE LEANDRO LANCE LLOYD
NATHANIEL NELSON NEIL NICHOLAS NOEL NORMAN NIKKO
OLIVER OSCAR OWEN
RANDY RAYMART RIAN ROY RUSSEL RYAN
SAMUEL SAM SEAN STEPHEN STEVEN STEVE SHERWIN
TONY TOMAS THOMAS TIMOTHY TRISTAN
VICTOR VINCENT VINCE VICENTE
WILLIAM WILFREDO WILSON
ZACHARY ZANDER
ARNEL ARNOLD ARIEL ARTHUR ARNIEL ARMAND ALBERT ALDRIN ALFRED ALEXANDER ALVIN ANDREW ANTHONY ANTONIO ARON AARON ADRIAN
BRYAN BRIAN BENJAMIN BENEDICT BENJIE BRYLLE BRAD BRENT
CHRISTIAN CEDRIC CLARK CLIFFORD CLYDE
""".split()

_F_NAMES = """
MARIA MARY MARIE MA MAE MAY ANN ANNE ANNA JANE JOY GRACE ROSE ROSE ROSEMARIE
ANGELA ANGELICA ANGELINE ANGELIE MARICEL MARICAR MARITES MARILYN MARIEL
JESSA JESSICA JENNY JENNIFER JOANNE JOAN JOANA JOANNA JOYCE JUDY JULIE JULIA
KAREN KATHLEEN KATHERINE KATRINA KAYE KIM KIMBERLY KRISTINE KRISTEL KRISTA KYLA
LEA LEAH LORNA LORRAINE LOVELY LOVE LYN LYNN LYKA LOUISE LIZA LIZEL LUZ
MELODY MELISSA MERRY MICHELLE MIKAELA MIKA MYRA MYRNA MARJORIE
NICOLE NIKKI NORA NORIE NENA NATASHA NAOMI
PRINCESS PEARL PAULA PAULINE PATRICIA PAMELA PRECIOUS
RACHEL REGINE REGINA RHEA RHEAL RIZA ROXANNE ROSALIE ROSALINA RUTH RHEANNE
SARAH SHAIRA SHARA SHARMAINE SHEILA SHELLA SHERRY SHIELA SOPHIA SOFIA STEPHANIE SUSAN
TERESA TRISHA TINA THERESE
VANESSA VERONICA VICTORIA VIVIAN
WENDY WINNIE
YVONNE YASMIN
ZYRA ZARA ZEN
AIRA AIZA ALTHEA ALYSSA AMY ANDREA ANGEL ANNABELLE APRIL ARLENE ARIANNE AUBREY
BEA BEATRIZ BERNADETTE BEVERLY BIANCA BLESSIE BLESSY
CAMILLE CARMELA CARMEN CAROL CAROLINE CATHERINE CHARITY CHARMAINE CHERRY CHERYL CHLOE CHRISTINE CINDY CLAIRE CLARISSA CRISTINA CRISTINE
DANICA DARLENE DIANA DIANE DONNA DESIREE
EMILY EMMA ERICA ESTHER EUNICE EVELYN
FAITH FATIMA FELICIA FRANCINE FRANCHESKA
GEMMA GENEVIEVE GERALDINE GLADYS GLORIA GLYZA
HANNAH HAZEL HEIDI HONEY
IRENE IRISH ISABEL ISABELLA IVY
""".split()


# Common English / international / biblical / Japanese given names that are
# absent or rare in the Bohol corpus (fallback when the lexicon has no entry).
_M_INTL = """
AARON ABEL ABRAHAM ADAM ADRIAN AIDAN ALAN ALBERTO ALDEN ALEXANDER ALFONSO ALFRED ALLAN ALONZO ALVIN AMIR AMOS ANDRE ANDRES
ANGELO ANTON ARCHIE ARMANDO ARNEL ARTURO ASHER ASHTON AUGUST AUSTIN AXEL BARRY BARTHOLOMEW BASTIAN BEN BENEDICT BENEDICTO
BENEDITO BERNARD BERNARDO BILLY BLAKE BOBBY BRANDON BRAYAN BRENDAN BRETT BRIAN BRODY BRUCE BRUNO BRYCE CALEB CALVIN CAMERON
CARLITO CARMELO CASPER CESAR CHAD CHANDLER CHASE CLAUDE CLIFF CLINT CLINTON COLE COLIN CONRAD CORNELIO CORY CRAIG CYRUS
DAMIAN DAMIEN DANTE DARIUS DARREN DARRYL DARIO DAVIN DEAN DEMETRIO DENIS DENVER DERICK DEREK DESMOND DEXTER DIEGO DION
DONALD DONATO DOUGLAS DUSTIN DUSTINE DWAYNE DWIGHT DYLAN EDDIE EDDY EDGARDO EDISON EDRIAN EDWIN EFREN ELDREN ELDRIN ELIAS
ELIJAH ELIOT ELLIOT ELISEO ELMO ELTON ELVIN ELVIS EMIL EMILIO EMMANUEL ENZO EPHRAIM ERNIE ESTEBAN ETHAN EUGENE EUGENIO
EVAN EZEKIEL EZRA FABIAN FELMAR FIDEL FLORENTINO FORTUNATO FRANK FRANKLIN FREDDIE FREDDY GAEL GARRY GARY GAVIN GENE
GERMAN GIDEON GINO GIOVANNI GLEN GORDON GRAHAM GRANT GUILLERMO GUS GUSTAVO HANS HAROLD HARRY HARVEY HECTOR HENRICK
HERMAN HOSEA HOSHEA HOWARD HUBERT HUGH HUGO HUMBERTO HUNTER IGNACIO INIGO ISAIAH ISAIAS ISIDRO ISRAEL IVAN JABEZ JACOB
JAIME JAKE JARED JARVIS JASPER JAVIER JAYDEN JEREMIAH JEREMY JETHRO JIM JOAQUIN JOB JODY JOHNSON JONAH JORGE
JOSIAH JOSUE JULIUS JUSTIN JUSTO KAREEM KEITH KEIFER KELVIN KEN KENNY KERVIN KIERAN KIRBY KIRK KLEIN KOBE KONRAD
KYNE LANCE LARRY LAURENCE LAZARO LEANDER LEONID LESTER LEVI LEWIS LIAM LINCOLN LIONEL LOUIS LUCIANO LUCIO LUDWIG MALCOLM
MANNY MANUEL MARCELO MARCIAL MARCOS MARIANO MARIO MARTIN MARVIN MASON MATEO MATHEW MATIAS MATTHEW MAURICE MAX MAXIMILIAN
MAXWELL MELVIN MIKHAIL MILES MITCHELL MOSES MYLES NATHAN NEO NEVILLE NICO NICOLAS NIKOLAI NOAH NOEL NOLI NOLASCO
OBED OMAR ORLANDO OSCAR OSMUND OTIS OTTO PABLO PATRIC PERCY PETER PHILIPPE PIERRE PRESTON QUENTIN QUINN RAFFY
RAJ RALPH RAMIL RAMIRO RAPHAEL RAUL RAY REGGIE REGINALD REMUS RENZ REUBEN REYNARD REYNOLD RHEYNARD RICO RIGOBERTO ROBBIE
ROBIN RODERICK RODNEY RODRIGO ROEL ROGER ROLLY ROMEL ROMULO RONALDO RONEL RONNEL ROSS ROWEL ROY ROYCE RUDY RUSSELL
SALVADOR SAMSON SANTIAGO SAUL SEBASTIAN SERGIO SETH SHAWN SHELDON SIDNEY SILVESTRE SIMON SOLOMON SPENCER STANLEY
STEFAN STERLING STUART TADEO TED TEDDY TERENCE TERRENCE THEODORE THEO TIMMY TITO TOBIAS TOBY TODD TRAVIS TREVOR TROY
TYLER TYRONE ULYSSES URIAH VAN VERNON VICENTE VIRGILIO VLADIMIR WALDO WALLY WALTER WARREN WAYNE WENDELL WESLEY WILBERT
WILFRED WILLY WINSTON WOLFGANG XAVIER ZACH ZACHARIAH ZACHARIAS ZEKE ZION REXXAR REXTON REXIE BRYLE JAYCEE
AKIRA HIRO HIROSHI KENJI KENTARO RYU SHINJI TAKESHI YUTO HARUTO RYOTA SORA
""".split()

_F_INTL = """
ABBY ABBIE ABIGAIL ADELA ADELE ADELINE ADRIANA ADRIENNE AGATHA AGNES AILEEN ALBA ALEXA ALEXANDRA ALEXIS ALICE ALICIA ALISON
ALLISON ALMA ALONDRA ALYANNA AMABELLE AMALIA AMANDA AMBER AMELIA AMELIE AMIE AMPARO ANABEL ANASTASIA ANETTE ANGELITA
ANGELLA ANGELYN ANJIE ANJELA ANJELICA ANNALYN ANNALIE ANNETTE ANNIE ANTONETTE ANTONIA ARABELLA ARIA ARIANA ASHLEY ASHLEIGH
AUDREY AURORA AVA AVERY AYESHA BABY BARBARA BECKY BELLA BELINDA BERNICE BERTHA BETH BETTY BIBIANA BLANCA BONNIE BRENDA
BRIANNA BRIDGET BRITTANY BROOKE CAITLIN CALLIE CAROLYN CASSANDRA CASSIE CECILIA CECILE CELESTE CELIA CELINE CHANEL CHANTAL
CHARLENE CHARLOTTE CHELSEA CHERIE CHERRYL CHRISTA CHRISTABEL CIARA CINDERELLA CLAIRE CLARA CLAUDIA COLLEEN CONCEPCION
CONSTANCE CORAZON CORINA CORNELIA COURTNEY CRYSTAL CYNTHIA DAISY DALIA DANA DANIELA DANIELLE DAPHNE DAWN DEBBIE DEBORAH
DELIA DELFINA DENISE DESTINY DIANNE DOLORES DOLLY DOMINIQUE DORA DOREEN DOROTHY EDNA EILEEN ELAINE ELEANOR ELENA
ELISA ELISE ELIZA ELIZABETH ELLA ELLEN ELLIE ELOISA ELSA ELVIRA EMELDA EMERALD EMILIA EMILIE ERIKA ERLINDA ESMERALDA
ESPERANZA ESTELLA ESTELLE ESTER ESTHER ETHEL EUGENIA EVA EVANGELINE EVE EVELYNE FAITHE FELICIDAD FELICITY FIONA FLORA
FLORENCE FLORDELIZA FRANCES FRANCESCA FREYA GABRIELA GABRIELLE GAIL GALE GEORGIA GERALYN GERTRUDE GINA GISELLE GLADY GLENDA
GRACIA GRETA GRETCHEN GUADALUPE GWEN GWENDOLYN HALEY HANA HANNA HAYLEY HEATHER HELEN HELENA HENRIETTA HILDA HOPE
IDA ILONA INES INGRID IRIS ISOLDE ISABELA IVANA JACKIE JACQUELINE JADA JAMILA JANELLE JANET JANICE JASMINE JAYME JEANETTE
JEANNE JENELYN JESSELYN JESSIE JILL JILLIAN JOCELYN JOSEFA JOSEPHINE JOSIE JOVELYN JOYLYN JUANA JULIANA JULIANNE
JULIET JULIETA JUNE KAILA KAITLYN KALEA KAMILA KARINA KARLA KASSANDRA KATE KATHY KATIE KAYLA KAYLEE KEISHA KELSEY KHLOE
KIARA KIERA KIRSTEN KRISTIN KRYSTAL LAILA LANI LARA LAUREN LAURA LAURICE LAVERNE LEANNE LEILA LEILANI LENY LENIE LEONORA
LESLIE LETICIA LIANA LILA LILIAN LILIBETH LILIA LILY LINA LINDA LISA LIZETTE LOIS LOLA LORAINE LORELIE LORETA LORETTA
LORI LOURDES LUCIA LUCILLE LUCY LUISA LUNA LYDIA MABEL MACY MADELINE MADISON MAGDALENA MAIA MALOU MARGARET MARGARITA
MARGIE MARIAH MARIANNE MARIBEL MARIETTA MARILOU MARINA MARISSA MARISOL MARLENE MARTHA MAUREEN MAXINE MAYA MAYETTE
MEGAN MELANIE MELBA MELINDA MERCEDES MERLE MIA MICHAELA MILA MILDRED MIRANDA MIRIAM MONA MONICA NADINE NANCY NANETTE
NATALIE NATHALIA NELLY NERISSA NICA NICHOLE NINA NOELLE NOREEN NORMA OCTAVIA OLGA OLIVIA OPHELIA PAIGE PANDORA
PATTY PAZ PEGGY PENELOPE PERLA PHOEBE PIA PILAR PRISCILLA QUEENIE RAMONA RAQUEL REBECCA REBECA REINA RENATA RHEANNA
RHODA RITA ROBERTA ROCHELLE ROMINA RONA ROSANNA ROSARIO ROSELYN ROSEMARY ROSITA ROWENA RUBY SABRINA SACHI SADIE SALLY SALOME
SAMANTHA SANDRA SANDY SAPPHIRE SASHA SELENA SELINA SERENA SHANAYA SHANELLE SHANNEN SHAWNA SHEENA SHELLY SHERYL SHIRLEY SIENNA SILVIA
SIMONE SKYLAR SOLEDAD SONIA SONYA STACY STELLA SUMMER SUZANNE SYLVIA TALIA TAMARA TANYA TASHA TATIANA THEA THELMA TIFFANY
TRICIA TRINA TRINIDAD UMA URSULA VALERIE VALENTINA VERA VERNA VIOLA VIOLETA VIOLET VIRGINIA VIVIEN WILMA XANDRA YASMINE
YOLANDA ZELDA ZOE ZOEY AIKO HARUKA MIKI SAKURA YUI YUKO HINATA MEI RIN RINA AYA
""".split()

# Names used by both sexes in the Philippines: a single token must not be able
# to push confidence very high on its own (its log-odds is capped).
_UNISEX = """
JADE KIM ANGEL JAMIE SHANE JESS JESSE KRIS ALEX SAM JAN JAY JUSTINE KYLE JORDAN JOSH
JEAN DEAN DREW LEE LOVE MARIAN MARION SKY SUNNY TAYLOR TRIXIE VAL BLAIR CASEY CHARLIE
CODY DANI EDEN ELI ERIN KEI KAI KELLY KENDALL MORGAN NICKY PAT RIO SAGE SAMMY TERRY
TONI LOUISE NIKKI CHRIS FRANCIS
""".split()

_OVERRIDE_STRENGTH = 2.0  # prior log-odds for curated M / F names
_UNISEX_CAP = 1.0  # max |log-odds| a unisex name can contribute

# Strong priors where the corpus is thin or known to be misleading
# (value = log-odds added to the corpus evidence; positive => male).
_FORCED = {
    "JHON": 4.0, "JHUN": 4.0, "JUN": 4.0, "JUNJUN": 4.0, "JUNIOR": 3.0, "JOHNREY": 4.0,
    "REY": 1.5, "RHEY": 2.5, "ARIEL": 2.5, "FRANCIS": 1.5,
    "JULIAN": 2.5, "RAJAH": 3.0, "JESSE": 2.0, "JESSEE": 2.0,
    "JOY": -4.0, "GRACE": -4.0, "MAE": -4.5, "MAY": -3.5, "ANN": -4.5, "ANNE": -4.0,
    "JANE": -4.5, "ROSE": -4.0, "MARIE": -4.5, "MARY": -4.5, "MARIA": -4.5,
    "LYN": -4.0, "LYNN": -4.0, "FE": -3.0,
}

# ---------------------------------------------------------------------------
# Morphology (unseen names)  -- ordered, longest ending first.
# value = prior log-odds (positive => male).  Deliberately weak.
# ---------------------------------------------------------------------------
_ENDINGS: tuple[tuple[str, float], ...] = (
    # female
    ("LYNN", -2.0), ("LYN", -2.0), ("ELLE", -2.0), ("ETTE", -2.2), ("ETTA", -2.0),
    ("INE", -1.4), ("ICE", -1.3), ("IZA", -1.8), ("ICA", -1.6), ("CEL", -1.4),
    ("SEL", -1.2), ("ENE", -1.2), ("ANA", -1.4), ("ISSA", -1.8), ("ESSA", -1.8),
    ("IE", -0.9), ("YN", -1.2),
    ("LA", -1.3), ("NA", -1.3), ("RA", -1.2), ("SA", -1.2), ("DA", -1.1),
    ("A", -1.1), ("Y", -0.5),
    # male
    ("ITO", 2.0), ("ARD", 1.8), ("ERT", 1.8), ("ICK", 1.6), ("MAR", 1.6), ("REX", 2.0),
    ("VEN", 1.6), ("TON", 1.4), ("SON", 1.4), ("RICK", 1.8), ("DEN", 1.2), ("LD", 1.4),
    ("IEL", 0.3), ("EL", 0.4), ("ON", 1.0), ("AN", 0.5), ("IN", 0.5), ("ES", 0.6),
    ("RO", 1.4), ("O", 1.3), ("ER", 0.5), ("OR", 0.8), ("US", 1.3), ("IS", 0.4), ("K", 1.0),
    ("D", 0.8), ("T", 0.6), ("B", 0.8), ("G", 0.6), ("N", 0.2), ("R", 0.3),
)
# Names ending in -A that are male, etc. (morphology exceptions)
_MORPH_EXCEPT = {"JOSHUA": 3.0, "NOAH": 2.0, "JONAH": 1.5, "ELIJAH": 2.0, "LUCA": 1.0, "ISAIAH": 2.0,
                 "JOSIAH": 2.0, "TOBIAS": 2.0, "MATTHIAS": 2.0, "ZACHARIAH": 2.0, "JEREMIAH": 2.5,
                 "RAJAH": 2.5, "MICAH": 2.0, "URIAH": 2.0, "HEZEKIAH": 2.0, "NEHEMIAH": 2.0}
# -AH is not a reliable female ending: Sarah / Hannah / Leah (F) but Noah /
# Jonah / Micah / Jeremiah / Rajah (M).  No morphology is applied to such names;
# they need a lexicon or curated hit.
_MORPH_NEUTRAL_ENDINGS = ("AH",)
CAP_MORPH_ONLY = 0.75  # max confidence when no given token is in the lexicon
CAP_RARE_HIT = 0.85  # max confidence when the only lexicon hits are rare (< RARE_N)
RARE_N = 5
UNSEEN_FIRST_SCALE = 0.3  # first-token morphology weight when a later token is a strong hit
MORPH_GAIN = 1.5  # scale of the morphology prior
MORPH_FADE = 2.0  # prior influence halves when a name has this many observations


# ---------------------------------------------------------------------------
# Lexicon
# ---------------------------------------------------------------------------
class Lexicon:
    """Aggregated given-name counts: {token: (male, female)} per position class."""

    def __init__(self, first: dict, later: dict, meta: dict | None = None,
                 endings: dict | None = None, prefixes: dict | None = None):
        self.first = {k: (int(v[0]), int(v[1])) for k, v in first.items()}
        self.later = {k: (int(v[0]), int(v[1])) for k, v in later.items()}
        self.meta = meta or {}
        # name-type level word-ending / word-start statistics {affix: (male, female)}
        self.endings = {k: (float(v[0]), float(v[1])) for k, v in (endings or {}).items()}
        self.prefixes = {k: (float(v[0]), float(v[1])) for k, v in (prefixes or {}).items()}

    @classmethod
    def from_json(cls, path: Path | str = LEXICON_PATH) -> "Lexicon":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(data.get("first", {}), data.get("later", {}), data.get("meta", {}),
                   data.get("endings", {}), data.get("prefixes", {}))

    def to_json(self) -> dict:
        return {
            "meta": self.meta,
            "first": {k: list(v) for k, v in sorted(self.first.items())},
            "later": {k: list(v) for k, v in sorted(self.later.items())},
            "endings": {k: [round(v[0], 2), round(v[1], 2)] for k, v in sorted(self.endings.items())},
            "prefixes": {k: [round(v[0], 2), round(v[1], 2)] for k, v in sorted(self.prefixes.items())},
        }


@lru_cache(maxsize=1)
def default_lexicon() -> Lexicon:
    try:
        return Lexicon.from_json(LEXICON_PATH)
    except (OSError, ValueError):
        return Lexicon({}, {}, {"error": "lexicon missing"})


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
def _strip_accents(s: str) -> str:
    s = s.replace("�", "N")  # mojibake for a lost Ñ (by far the most common case)
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_tokens(text: str) -> list[str]:
    """Uppercase, strip accents/punctuation, split to alphabetic tokens."""
    if not text:
        return []
    s = _strip_accents(str(text)).upper()
    return re.findall(r"[A-Z]+", s)


def split_given(tokens: list[str]) -> tuple[list[str], list[str]]:
    """Separate generational suffixes from name tokens; drop initials."""
    names: list[str] = []
    sfx: list[str] = []
    for t in tokens:
        if t in SUFFIXES and (names or t in {"JR", "SR"}):
            sfx.append(t)
        elif len(t) >= 2:
            names.append(t)
    return names, sfx


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------
AFFIX_MIN = 4.0  # minimum name-types an ending/prefix needs before it is trusted
AFFIX_ALPHA = 1.0
END_W = 0.65
PRE_W = 0.35
LEARNED_WEIGHT = 0.8  # blend: learned affix stats vs hand-written endings


def _affix_lo(table: dict, affixes: list[str]) -> tuple[float, str]:
    """Log-odds from the longest sufficiently-supported affix; (0, "") if none."""
    for a in affixes:
        m, f = table.get(a, (0.0, 0.0))
        if m + f >= AFFIX_MIN:
            return math.log((m + AFFIX_ALPHA) / (f + AFFIX_ALPHA)), a
    return 0.0, ""


def learned_morphology(token: str, lex: "Lexicon") -> tuple[float, str]:
    """Log-odds for an unseen name from learned ending/prefix statistics."""
    if not lex.endings or len(token) < 3 or token.endswith(_MORPH_NEUTRAL_ENDINGS):
        return 0.0, ""
    e_lo, e = _affix_lo(lex.endings, [token[-k:] for k in (4, 3, 2, 1) if len(token) > k])
    p_lo, p = _affix_lo(lex.prefixes, [token[:k] for k in (4, 3) if len(token) > k])
    lo = END_W * e_lo + PRE_W * p_lo
    note = "/".join(x for x in (f"-{e}" if e else "", f"{p}-" if p else "") if x)
    return lo, note


def morphology_prior(token: str) -> tuple[float, str]:
    """Return (log-odds, ending) from word endings; (0.0, "") when no rule matches."""
    if token in _MORPH_EXCEPT:
        return _MORPH_EXCEPT[token], "exception"
    if token.endswith(_MORPH_NEUTRAL_ENDINGS):
        return 0.0, ""
    if len(token) < 3:
        return 0.0, ""
    for end, lo in _ENDINGS:
        if token.endswith(end) and len(token) > len(end):
            return lo, "-" + end.lower()
    return 0.0, ""


_M_SET = set(_M_NAMES) | set(_M_INTL)
_F_SET = set(_F_NAMES) | set(_F_INTL)
_BOTH = _M_SET & _F_SET  # listed under both sexes: treat as unisex
_M_SET -= _BOTH
_F_SET -= _BOTH
_UNISEX_SET = set(_UNISEX) | _BOTH
# unisex / forced names are handled separately from the plain M/F lists
for _grp in (_M_SET, _F_SET):
    _grp -= _UNISEX_SET
    _grp -= set(_FORCED)


def token_log_odds(
    token: str, pos: int, lex: Lexicon
) -> tuple[float, str, int]:
    """
    Log-odds (positive => male) for one token at a position (before position
    weighting), a short description, and the *support* level:
    0 = morphology / nothing, 1 = rare lexicon hit (< RARE_N observations),
    2 = well-supported lexicon hit or curated name.
    """
    primary, other = (lex.first, lex.later) if pos == 0 else (lex.later, lex.first)
    m1, f1 = primary.get(token, (0, 0))
    m2, f2 = other.get(token, (0, 0))
    m = m1 + CROSS_TABLE * m2
    f = f1 + CROSS_TABLE * f2
    n = m + f
    notes = []

    curated_prior = 0.0
    curated = False
    if token in _FORCED:
        curated_prior, curated = _FORCED[token], True
    elif token in _M_SET:
        curated_prior, curated = _OVERRIDE_STRENGTH, True
    elif token in _F_SET:
        curated_prior, curated = -_OVERRIDE_STRENGTH, True

    # morphology prior (first-position tokens only; curated names don't need it)
    prior = 0.0
    if pos == 0 and not curated:
        mp, ending = morphology_prior(token)
        lm, lnote = learned_morphology(token, lex)
        if lnote:
            prior = LEARNED_WEIGHT * lm + (1 - LEARNED_WEIGHT) * mp
        elif ending:
            prior = mp
        if (ending or lnote) and n < 3:
            notes.append(f"morphology {lnote or ending}")
    # count evidence + a morphology prior whose influence fades as counts grow
    lo = math.log((m + ALPHA) / (f + ALPHA))
    if prior:
        lo += MORPH_GAIN * prior / (1.0 + n / MORPH_FADE)
    if n > 0:
        notes.insert(0, f"lexicon {m1 + m2}M/{f1 + f2}F")
    if curated:
        lo += curated_prior
        notes.append("curated")
    if token in _UNISEX_SET:
        lo = max(-_UNISEX_CAP, min(_UNISEX_CAP, lo))
        notes.append("unisex")

    if curated or n >= RARE_N:
        support = 2
    elif n > 0:
        support = 1
    else:
        support = 0
    return lo, ", ".join(notes), support


def infer_sex(
    first_name: str,
    middle_name: str = "",
    full_given: str = "",
    suffix: str = "",
    lexicon: Lexicon | None = None,
) -> tuple[str, float, str]:
    """
    Infer sex from a Filipino given name.

    Args:
        first_name: first-name field ("KYLA JADE", "MA. LUISA", "JOHN").
        middle_name: middle-name field (usually the mother's maiden surname;
            only used with MID_WEIGHT, default ignored).
        full_given: optional complete given-name string (first + second given
            names, possibly with the middle name appended).  If supplied its
            tokens are used after ``first_name``'s.
        suffix: optional name extension ("JR.", "SR.", "III").
        lexicon: optional Lexicon (defaults to backend/data/given_name_gender.json).

    Returns:
        (sex, confidence, reason): sex is "M", "F" or "" when confidence < 0.6.
        confidence is in [0.5, 1.0] (max of P(M), P(F)); 0.0 if no input.
    """
    lex = lexicon or default_lexicon()
    first_tokens = normalize_tokens(first_name)
    given_tokens = normalize_tokens(full_given)
    if first_tokens and given_tokens[: len(first_tokens)] != first_tokens:
        tokens = first_tokens + given_tokens
    else:
        tokens = given_tokens or first_tokens

    names, sfx_tokens = split_given(tokens)
    for s in normalize_tokens(suffix):
        if s in SUFFIXES:
            sfx_tokens.append(s)

    if not names and not sfx_tokens:
        return "", 0.0, "no name"

    total = 0.0
    parts: list[str] = []
    support = 0  # best evidence level seen: 0 morphology only, 1 rare hit, 2 strong

    # "MA." / "MARIA" prefix -> Filipino abbreviation of Maria
    if names and names[0] in MARIA_PREFIXES:
        if names[0] == "MA" or len(names) > 1:
            total -= MA_LO
            support = 2
            parts.append(f"{names[0]}->Maria prefix (F)")
            names = names[1:]

    scored = [(i, tok) + token_log_odds(tok, i, lex) for i, tok in enumerate(names)]
    # Unseen first name but a well-supported later token (e.g. KYNE REYNARD):
    # the known token dominates and first-token morphology is discounted.
    later_strong = any(i > 0 and sup == 2 for i, _, _, _, sup in scored)
    for i, tok, lo, note, sup in scored:
        if i > 0 and sup == 0:
            continue  # unknown later tokens are usually the mother's surname
        w = POS_WEIGHTS[min(i, len(POS_WEIGHTS) - 1)]
        if later_strong and i == 0 and sup == 0:
            w = UNSEEN_FIRST_SCALE
        elif later_strong and i > 0 and sup == 2:
            w = max(w, 1.0)
        support = max(support, sup)
        total += w * lo
        parts.append(f"{tok}{'' if i == 0 else '@' + str(i)}:{lo * w:+.2f}" + (f" ({note})" if note else ""))

    for s in sfx_tokens:
        lo_s = SUFFIX_LO.get(s, SUFFIX_LO.get(s[:2], 0.0))
        total += lo_s
        if lo_s >= 2.0:
            support = 2  # JR./SR./III is real evidence, not a morphology guess
        parts.append(f"suffix {s}")

    if MID_WEIGHT and middle_name:
        for tok in split_given(normalize_tokens(middle_name))[0]:
            lo, _, sup = token_log_odds(tok, 1, lex)
            if sup:
                total += MID_WEIGHT * lo

    p_male = 1.0 / (1.0 + math.exp(-total / TEMPERATURE))
    conf = max(p_male, 1.0 - p_male)
    # calibration: names with no (or only rare) lexicon support are guesses
    if support == 0:
        conf = min(conf, CAP_MORPH_ONLY)
    elif support == 1:
        conf = min(conf, CAP_RARE_HIT)
    sex = "M" if p_male >= 0.5 else "F"
    reason = "; ".join(parts) if parts else "no evidence"
    if conf < MIN_CONFIDENCE:
        return "", round(conf, 3), "low confidence: " + reason
    return sex, round(conf, 3), reason


_SEX_ALIASES = {"m": "M", "male": "M", "boy": "M", "f": "F", "female": "F", "girl": "F"}


def resolve_gender(raw: str, firstname: str, extension: str = "") -> tuple[str, str, float]:
    """
    Decide a record's gender: normalise the PDF value to "M"/"F" (unrecognised
    values are kept as-is), or infer it from the first name when blank.

    Returns:
        (gender, source, confidence): source is "pdf", "inferred" or "" (nothing
        known); confidence is 1.0 for PDF values, the inference score otherwise.
    """
    raw = (raw or "").strip()
    if raw:
        return _SEX_ALIASES.get(raw.lower(), raw), "pdf", 1.0
    tokens = normalize_tokens(firstname)
    if tokens:
        sex, conf, _ = infer_sex(tokens[0], "", firstname, extension)
        if sex:
            return sex, "inferred", conf
    return "", "", 0.0


def _main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m backend.gender", description="Infer sex from a Filipino given name")
    ap.add_argument("first", help="first name (may include second given name)")
    ap.add_argument("middle", nargs="?", default="", help="middle name (optional, mostly ignored)")
    ap.add_argument("--given", default="", help="full given-name string")
    ap.add_argument("--suffix", default="", help="JR., SR., III ...")
    args = ap.parse_args(argv)
    sex, conf, reason = infer_sex(args.first, args.middle, args.given, args.suffix)
    print(f"{sex},{conf:.2f},{reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
