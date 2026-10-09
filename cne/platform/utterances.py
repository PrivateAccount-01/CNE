"""Bounded utterance templates and a timed, restricted legacy regex adapter."""
from functools import lru_cache
import re
import regex
from cne.platform.errors import GrammarValidationError

MAX_QUERY = 4096
TYPES = {
    "string": r"[^\r\n]{1,128}?",
    "number": r"-?\d{1,18}(?:\.\d{1,12})?",
    "integer": r"-?\d{1,18}",
    "date": r"\d{4}-\d{2}-\d{2}",
}


@lru_cache(maxsize=2048)
def compile_mapping(template=None, pattern=None):
    if bool(template) == bool(pattern):
        raise GrammarValidationError("Exactly one template or legacy pattern required")
    text = template or pattern
    if len(text) > 1024:
        raise GrammarValidationError("Grammar too long")
    if template:
        parts = []
        end = 0
        names = set()
        for slot in re.finditer(
            r"\{([a-zA-Z_]\w*):(string|number|integer|date)\}", template
        ):
            name, kind = slot.groups()
            if name in names:
                raise GrammarValidationError("Duplicate template slot")
            names.add(name)
            parts.extend(
                [re.escape(template[end : slot.start()]), f"(?P<{name}>{TYPES[kind]})"]
            )
            end = slot.end()
        parts.append(re.escape(template[end:]))
        pattern = "".join(parts)
        if "{" in re.sub(
            r"\{([a-zA-Z_]\w*):(string|number|integer|date)\}", "", template
        ):
            raise GrammarValidationError("Unsupported template slot")
    else:
        try:
            from re import _parser as parser, _constants as c
        except ImportError:
            import sre_parse as parser, sre_constants as c
        try:
            tree = parser.parse(pattern, 0)
        except re.error as exc:
            raise GrammarValidationError("Invalid legacy pattern") from exc

        def check(nodes, repeated=False):
            for op, arg in nodes:
                if op in (c.GROUPREF, c.ASSERT, c.ASSERT_NOT, c.GROUPREF_EXISTS):
                    raise GrammarValidationError("Unsafe regex operation")
                if op in (c.MAX_REPEAT, c.MIN_REPEAT):
                    lo, hi, child = arg
                    if hi > 1 and repeated:
                        raise GrammarValidationError("Nested repeating pattern")
                    check(child, repeated or hi > 1)
                elif op == c.SUBPATTERN:
                    check(arg[-1], repeated)
                elif op == c.BRANCH:
                    if repeated:
                        raise GrammarValidationError("Repeating alternation")
                    for child in arg[1]:
                        check(child, repeated)

        check(tree)
    try:
        return regex.compile(pattern, regex.IGNORECASE)
    except regex.error as exc:
        raise GrammarValidationError("Invalid grammar") from exc


def match_mapping(mapping, query):
    if len(query) > MAX_QUERY:
        raise GrammarValidationError("Request too long")
    compiled = compile_mapping(mapping.get("template"), mapping.get("pattern"))
    try:
        return compiled.fullmatch(query, timeout=0.01)
    except TimeoutError as exc:
        raise GrammarValidationError("Grammar match deadline exceeded") from exc


def validate_mappings(manifest):
    mappings = manifest.schemas.get("intents", [])
    if len(mappings) > 64:
        raise GrammarValidationError("Too many intents")
    for m in mappings:
        compile_mapping(m.get("template"), m.get("pattern"))
