"""Translation workflow without GNU gettext (handy on shared hosting / Windows).

    python scripts/i18n.py extract   # update locale/ar/LC_MESSAGES/django.po from code + templates
    python scripts/i18n.py compile   # build django.mo (also run by the Dockerfile)

Source strings are written in French; Arabic is the translation.
Requires `pip install babel` (development only). With GNU gettext installed you
can use `django-admin makemessages -l ar` and `compilemessages` instead.
"""
import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from babel.messages.catalog import Catalog  # noqa: E402
from babel.messages.extract import extract  # noqa: E402
from babel.messages.mofile import write_mo  # noqa: E402
from babel.messages.pofile import read_po, write_po  # noqa: E402

PO = ROOT / "locale" / "ar" / "LC_MESSAGES" / "django.po"
KEYWORDS = {"_": None, "N_": None, "gettext": None, "gettext_lazy": None, "gettext_noop": None, "ngettext": (1, 2),
            "ngettext_lazy": (1, 2), "pgettext": ((1, "c"), 2), "pgettext_lazy": ((1, "c"), 2),
            "npgettext": ((1, "c"), 2, 3)}


def sources():
    for base in ("apps", "config", "templates"):
        for path in sorted((ROOT / base).rglob("*")):
            if "migrations" in path.parts or "__pycache__" in path.parts or path.name in ("tests.py", "factories.py"):
                continue
            if "management" in path.parts:
                continue
            if path.suffix in (".py", ".html", ".txt"):
                yield path


def extract_all():
    import django

    django.setup()
    from django.utils.translation.template import templatize

    found = {}
    for path in sources():
        text = path.read_text(encoding="utf-8")
        if path.suffix != ".py":
            # Babel's tokenizer is strict about indentation; templatize keeps
            # strings on one line (repr), so stripping indentation is safe.
            text = "\n".join(line.strip() for line in templatize(text, origin=str(path)).splitlines())
        rel = str(path.relative_to(ROOT))
        for lineno, msgid, _comments, context in extract("python", io.BytesIO(text.encode()), keywords=KEYWORDS,
                                                          options={"encoding": "utf-8"}):
            found.setdefault((msgid, context), []).append((rel, lineno))
    return found


def is_translated(m):
    if isinstance(m.string, (tuple, list)):
        return all(m.string)
    return bool(m.string)


def cmd_extract():
    old = read_po(PO.open("rb"), locale="ar") if PO.exists() else Catalog(locale="ar")
    cat = Catalog(locale="ar", project="Moucharaka", charset="utf-8", fuzzy=False)
    for (msgid, ctx), locs in extract_all().items():
        key = msgid[0] if isinstance(msgid, tuple) else msgid
        prev = old.get(key, ctx)
        if prev is not None and is_translated(prev):
            string = prev.string
        else:
            string = tuple([""] * 6) if isinstance(msgid, tuple) else ""
        cat.add(msgid, string=string, locations=locs[:3], context=ctx)
    PO.parent.mkdir(parents=True, exist_ok=True)
    with PO.open("wb") as f:
        write_po(f, cat, width=0, sort_output=False)
    missing = [m.id for m in cat if m.id and not is_translated(m)]
    print(f"{len(cat)} messages, {len(missing)} untranslated -> {PO}")
    return missing


def cmd_compile():
    cat = read_po(PO.open("rb"), locale="ar")
    with PO.with_suffix(".mo").open("wb") as f:
        write_mo(f, cat, use_fuzzy=False)
    # French is the source language, but Django falls back to the *default*
    # language (LANGUAGE_CODE, often "ar") for strings missing from a catalog.
    # An identity French catalog stops French pages from showing Arabic.
    fr = Catalog(locale="fr", project="Moucharaka", charset="utf-8")
    for m in cat:
        if m.id:
            fr.add(m.id, string=tuple(m.id) if isinstance(m.id, tuple) else m.id, context=m.context)
    fr_po = ROOT / "locale" / "fr" / "LC_MESSAGES" / "django.po"
    fr_po.parent.mkdir(parents=True, exist_ok=True)
    with fr_po.open("wb") as f:
        write_po(f, fr, width=0, sort_output=False)
    with fr_po.with_suffix(".mo").open("wb") as f:
        write_mo(f, fr)
    print(f"compiled {len(cat)} messages (ar) + identity catalog (fr)")


if __name__ == "__main__":
    {"extract": cmd_extract, "compile": cmd_compile}[sys.argv[1] if len(sys.argv) > 1 else "extract"]()
