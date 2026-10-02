#!/usr/bin/env python3
"""
WCAG contrast ratio checker for two hex colors, a whole palette, or the full
pairing matrix of a palette.

Why this exists: a palette (whether hand-picked, extracted from a reference
image, or a user-supplied brand color) can look fine as a swatch and still
fail contrast once it's actually used as text-on-background or a button
label. The easiest miss is checking body-text-on-background and stopping
there: a Primary/Accent color can pass that check and still be illegible
as a button fill with white label text. This script checks pairs directly
against the real WCAG math instead of eyeballing it.

The deeper miss is time: a palette that passed for the pairings you enumerated
at authoring time can still fail the moment the model uses two of its colors
in a pairing you never listed. --matrix answers "which of these colors may
legally touch which," so the lock certifies the palette as *usable*, not just
as authored. See the contract described in references/style-lock-format.md.

Usage:
    # single pair
    python3 check_contrast.py 050315 fbfbfe
    python3 check_contrast.py "#050315" "#FBFBFE"

    # a five-role palette: checks the critical pairings and PASS/FAILs
    python3 check_contrast.py --palette text=050315 bg=fbfbfe primary=2f27ce \
        secondary=dedcff accent=433bff

    # the full pairing matrix: every color pair, classified by which floor it
    # clears, plus a legal-pairings summary to record in the style lock.
    # Include a label color (e.g. on-primary=ffffff) to see button-label legality.
    python3 check_contrast.py --matrix text=e6e6ea bg=0b0d12 surface=161a21 \
        primary=047857 accent=34d399 border=232a33 on-primary=ffffff

    # machine-readable output for pair, palette, and matrix modes
    python3 check_contrast.py --json --matrix text=e6e6ea bg=0b0d12

    # re-check every pairing declared Text-safe in an existing style lock
    python3 check_contrast.py --style-lock .tastemaker/style-lock.md

JSON schema version 1 always includes ``schema_version``, ``mode``, ``passed``,
and ``pairs``. Each pair contains its names, normalized #RRGGBB colors, ratio
(rounded to four decimals), classification, and, when applicable, its required
floor and pass result. Matrix output also includes ``legal_pairings`` grouped
as ``text_safe``, ``ui_safe``, and ``decorative``. Keys are sorted so repeated
runs with the same ordered input are byte-for-byte stable.

Exit code: --palette and single-pair exit nonzero if any checked pairing fails
its floor. --matrix is a report and exits 0 (it does not know each pair's
intended use, so it classifies rather than pass/fails). --style-lock exits
nonzero when any pairing recorded as Text-safe is now below 4.5:1.
"""

import json
import re
import sys
from pathlib import Path

AA_NORMAL = 4.5  # body text on its background
AA_LARGE_OR_UI = 3.0  # large text, UI components, graphical objects (WCAG 1.4.11)
SCHEMA_VERSION = 1


def _linearize(c):
    c = c / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _normalize_hex(hex_color):
    value = hex_color.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"expected a 6-digit hex color, got {value!r}")
    int(value, 16)
    return value.lower()


def _luminance(hex_color):
    hex_color = _normalize_hex(hex_color)
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _linearize(r) + 0.7152 * _linearize(g) + 0.0722 * _linearize(b)


def ratio(hex1, hex2):
    l1, l2 = _luminance(hex1), _luminance(hex2)
    l1, l2 = max(l1, l2), min(l1, l2)
    return (l1 + 0.05) / (l2 + 0.05)


def _classification(value):
    if value >= AA_NORMAL:
        return "text-safe"
    if value >= AA_LARGE_OR_UI:
        return "ui-safe"
    return "decorative"


def _pair_result(label, first, second, first_hex, second_hex, floor=None):
    value = ratio(first_hex, second_hex)
    result = {
        "classification": _classification(value),
        "first": first,
        "first_hex": f"#{_normalize_hex(first_hex)}",
        "label": label,
        "ratio": round(value, 4),
        "second": second,
        "second_hex": f"#{_normalize_hex(second_hex)}",
    }
    if floor is not None:
        result["floor"] = floor
        result["passes"] = value >= floor
    return result


def report(label, hex1, hex2, floor=AA_NORMAL):
    r = ratio(hex1, hex2)
    status = "PASS" if r >= floor else "FAIL"
    print(
        f"[{status}] {label}: {r:.2f}:1 (floor {floor}:1) — "
        f"#{hex1.lstrip('#')} vs #{hex2.lstrip('#')}"
    )
    return r >= floor


def parse_roles(args):
    roles = {}
    for kv in args:
        if "=" not in kv:
            raise ValueError(f"Bad argument (expected role=hex): {kv}")
        key, value = kv.split("=", 1)
        if not key:
            raise ValueError(f"Bad argument (role is empty): {kv}")
        roles[key] = _normalize_hex(value)
    return roles


def _matrix_results(roles):
    names = list(roles.keys())
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            first, second = names[i], names[j]
            pairs.append(
                _pair_result(
                    f"{first}/{second}",
                    first,
                    second,
                    roles[first],
                    roles[second],
                )
            )
    pairs.sort(key=lambda pair: -pair["ratio"])
    legal = {
        "text_safe": [pair["label"] for pair in pairs if pair["classification"] == "text-safe"],
        "ui_safe": [pair["label"] for pair in pairs if pair["classification"] == "ui-safe"],
        "decorative": [pair["label"] for pair in pairs if pair["classification"] == "decorative"],
    }
    return pairs, legal


def run_matrix(roles):
    names = list(roles.keys())
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            r = ratio(roles[a], roles[b])
            pairs.append((a, b, r))
    pairs.sort(key=lambda p: -p[2])

    print(f"== Contrast matrix ({len(roles)} roles, {len(pairs)} pairs) ==")
    for a, b, r in pairs:
        if r >= AA_NORMAL:
            cls = "text-safe (>=4.5)"
        elif r >= AA_LARGE_OR_UI:
            cls = "UI-safe  (>=3.0)"
        else:
            cls = "decorative (<3.0)"
        print(f"  {a:<12} x {b:<12} {r:6.2f}  {cls}")

    print()
    print("== Legal pairings (record these in the style lock) ==")
    text_safe = [f"{a}/{b}" for a, b, r in pairs if r >= AA_NORMAL]
    ui_safe = [f"{a}/{b}" for a, b, r in pairs if AA_LARGE_OR_UI <= r < AA_NORMAL]
    decorative = [f"{a}/{b}" for a, b, r in pairs if r < AA_LARGE_OR_UI]
    print(
        "  Text-safe   (body text, links, button labels on a fill; >=4.5): "
        f"{', '.join(text_safe) or 'none'}"
    )
    print(
        "  UI-safe     (large text, icons, and borders that convey state; >=3.0 and <4.5): "
        f"{', '.join(ui_safe) or 'none'}"
    )
    print(
        "  Decorative  (below 3.0; fine as a subtle hairline, must NOT be the only thing conveying state): "
        f"{', '.join(decorative) or 'none'}"
    )
    return pairs


def _palette_results(roles):
    missing = {"text", "bg"} - roles.keys()
    if missing:
        raise ValueError(f"--palette requires at least text= and bg=; missing {missing}")

    pairs = [
        _pair_result(
            "body text / background", "text", "bg", roles["text"], roles["bg"], AA_NORMAL
        )
    ]
    requirements = [pairs[-1]["passes"]]

    if "primary" in roles:
        white = _pair_result(
            "white label / primary fill",
            "white",
            "primary",
            "ffffff",
            roles["primary"],
            AA_NORMAL,
        )
        dark = _pair_result(
            f"dark text ({roles['text']}) / primary fill",
            "text",
            "primary",
            roles["text"],
            roles["primary"],
            AA_NORMAL,
        )
        visibility = _pair_result(
            "primary / background (visibility, UI-component floor)",
            "primary",
            "bg",
            roles["primary"],
            roles["bg"],
            AA_LARGE_OR_UI,
        )
        pairs.extend([white, dark, visibility])
        requirements.extend([white["passes"] or dark["passes"], visibility["passes"]])

    if "accent" in roles:
        accent = _pair_result(
            "accent / background (visibility + hyperlink-text floor)",
            "accent",
            "bg",
            roles["accent"],
            roles["bg"],
            AA_LARGE_OR_UI,
        )
        pairs.append(accent)
        requirements.append(accent["passes"])

    return pairs, all(requirements)


_STYLE_ROLE_ALIASES = {
    "background": "bg",
    "button-label-color": "on-primary",
    "dark-surface": "dark",
    "on-dark-text": "on-dark",
    "text-muted": "muted",
    "text-primary": "text",
}


def _style_role(label):
    normalized = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return _STYLE_ROLE_ALIASES.get(normalized, normalized)


def parse_style_lock(path):
    text = Path(path).read_text(encoding="utf-8")
    palette_match = re.search(r"(?ms)^## Palette\s*$\n(.*?)(?=^##\s|\Z)", text)
    if not palette_match:
        raise ValueError(f"{path}: missing '## Palette' section")

    roles = {}
    for label, color in re.findall(
        r"(?m)^-\s+([^:]+):\s*#([0-9a-fA-F]{6})\b", palette_match.group(1)
    ):
        roles[_style_role(label)] = color.lower()

    contract_match = re.search(r"(?m)^-\s+Text-safe\s*\(>=4\.5\):\s*(.+)$", text)
    if not contract_match:
        raise ValueError(f"{path}: missing Text-safe (>=4.5) contract line")

    pairings = []
    for item in contract_match.group(1).split(","):
        name = re.sub(r"\s*\([^)]*\)\s*$", "", item).strip().strip("`")
        if name.lower() == "none":
            continue
        parts = [part.strip() for part in name.split("/")]
        if len(parts) != 2 or not all(parts):
            raise ValueError(f"{path}: invalid Text-safe pairing {name!r}")
        pairings.append(tuple(parts))

    if not pairings:
        raise ValueError(f"{path}: Text-safe contract contains no pairings")
    return roles, pairings


def _style_lock_results(path):
    roles, pairings = parse_style_lock(path)
    missing = sorted({role for pair in pairings for role in pair if role not in roles})
    if missing:
        raise ValueError(f"{path}: Text-safe pairings reference missing palette roles: {', '.join(missing)}")

    results = [
        _pair_result(
            f"{first}/{second}",
            first,
            second,
            roles[first],
            roles[second],
            AA_NORMAL,
        )
        for first, second in pairings
    ]
    return results, all(pair["passes"] for pair in results)


def _json_output(mode, pairs, passed, **extra):
    payload = {
        "mode": mode,
        "pairs": pairs,
        "passed": passed,
        "schema_version": SCHEMA_VERSION,
        **extra,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def _pop_json_flag(args):
    count = args.count("--json")
    if count > 1:
        raise ValueError("--json may only be specified once")
    if count:
        args.remove("--json")
    return bool(count)


def main():
    args = sys.argv[1:]
    try:
        json_mode = _pop_json_flag(args)
        if not args:
            print(__doc__, file=sys.stderr)
            return 1

        if args[0] == "--style-lock":
            if len(args) != 2:
                raise ValueError("--style-lock requires exactly one file path")
            pairs, passed = _style_lock_results(args[1])
            if json_mode:
                _json_output("style-lock", pairs, passed, style_lock=args[1])
            else:
                print(f"== Style-lock text-safe regression check ({args[1]}) ==")
                for pair in pairs:
                    status = "PASS" if pair["passes"] else "FAIL"
                    print(
                        f"[{status}] {pair['label']}: {pair['ratio']:.2f}:1 "
                        f"(floor {AA_NORMAL}:1) - {pair['first_hex']} vs {pair['second_hex']}"
                    )
            return 0 if passed else 1

        if args[0] == "--matrix":
            roles = parse_roles(args[1:])
            if len(roles) < 2:
                raise ValueError("--matrix needs at least two role=hex colors.")
            if json_mode:
                pairs, legal = _matrix_results(roles)
                _json_output("matrix", pairs, True, legal_pairings=legal)
            else:
                run_matrix(roles)
            return 0

        if args[0] == "--palette":
            roles = parse_roles(args[1:])
            if json_mode:
                pairs, passed = _palette_results(roles)
                _json_output("palette", pairs, passed)
                return 0 if passed else 1

            missing = {"text", "bg"} - roles.keys()
            if missing:
                raise ValueError(f"--palette requires at least text= and bg=; missing {missing}")

            all_pass = report("body text / background", roles["text"], roles["bg"], AA_NORMAL)
            if "primary" in roles:
                white_ok = report(
                    "white label / primary fill", "ffffff", roles["primary"], AA_NORMAL
                )
                dark_ok = report(
                    f"dark text ({roles['text']}) / primary fill",
                    roles["text"],
                    roles["primary"],
                    AA_NORMAL,
                )
                if not (white_ok or dark_ok):
                    print(
                        f"  -> NEITHER white nor {roles['text']} text is readable on "
                        f"primary #{roles['primary']} — darken/lighten primary, don't "
                        "just pick a label color and hope."
                    )
                all_pass &= white_ok or dark_ok
                all_pass &= report(
                    "primary / background (visibility, UI-component floor)",
                    roles["primary"],
                    roles["bg"],
                    AA_LARGE_OR_UI,
                )
            if "accent" in roles:
                all_pass &= report(
                    "accent / background (visibility + hyperlink-text floor)",
                    roles["accent"],
                    roles["bg"],
                    AA_LARGE_OR_UI,
                )
            return 0 if all_pass else 1

        if len(args) != 2:
            raise ValueError(
                "Usage: check_contrast.py <hex1> <hex2>  OR  "
                "--palette role=hex ...  OR  --matrix role=hex ..."
            )
        pair = _pair_result("given pair", "color-1", "color-2", args[0], args[1], AA_NORMAL)
        if json_mode:
            _json_output("pair", [pair], pair["passes"])
        else:
            report("given pair", args[0], args[1], AA_NORMAL)
        return 0 if pair["passes"] else 1
    except (OSError, ValueError) as error:
        if "json_mode" in locals() and json_mode:
            print(
                json.dumps(
                    {
                        "error": str(error),
                        "passed": False,
                        "schema_version": SCHEMA_VERSION,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
