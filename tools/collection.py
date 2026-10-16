#!/usr/bin/env python3
"""Write data/collection.tsv: one row per retail mount and battle pet that wow-mod-retail-library
has a look for, with what the build needs to make it a spell and an item.

    python3 collection.py --census <census out dir> --db2 ~/retail-cache/db2 \\
        --listfile ~/retail-cache/community-listfile.csv --library ../mod-retail-library \\
        --spell-patch patch-z80-spells-and-items.MPQ --taken ../mod-retail-pets/data/pets.tsv

The census is wow-mod-retail-creatures' tools/census.py run with --models (the same one the
library's looks.tsv came from); --db2 is the folder it cached retail's tables in (it needs Mount,
MountCapability, MountTypeXCapability, SpellMisc, BattlePetSpecies and Creature). --listfile is
the community listfile, which names the icons. --spell-patch is the realm's patch with the full
Spell.dbc and SkillLineAbility.dbc: a mount or pet the client already has (a stock mount whose
look retail redrew, say) is left out, so nobody owns two Chargers. So is one that another module
already makes learnable: --taken names that module's list (any tsv with `display` and
`retail_display` columns, like wow-mod-retail-pets' pets.tsv), and a mount or pet that wears any
of its looks is left out.

One retail mount or pet is one row, however many looks it has: retail picks one of a mount's
looks (by faction, or at random) and one of a pet's (its breed), and here the creature wears all
of them at random. A row's id is its spell, item and creature id:

    mount  400000 + retail mount id      pet  410000 + retail battle pet species id

so it never moves, whatever is added or dropped later.
"""
import argparse
import csv
import os
import re
import sys
import tempfile

import dbcmpq

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data", "collection.tsv")
MOUNT_BASE, PET_BASE = 400000, 410000
LIBRARY_OFFSET = 200000  # a library look's display id is 200000 + its retail display id

# Retail's mount capability flags: 0x2 = can fly. A mount type with a flying capability is a
# flyer here, except the seahorses (254), which fly only in Nazjatar.
CAPABILITY_FLY = 0x2
WATER_TYPES = {254}
# Left out: ghost mounts (type 242, retail puts a dead player on one) and self mounts (Mount
# flag 0x2: the player turns into the creature, which a mounted aura can't do).
GHOST_TYPE = 242
MOUNT_FLAG_SELF = 0x2
# A creature has at most four looks (creature_template_model.Idx 0-3, a check in the core's
# schema): a mount with more keeps retail's first four.
MAX_LOOKS = 4
# The module's own block: ids in it that the spell patch has are this module's rows, not stock ones.
BLOCK = (400000, 419999)

# Placeholder and test rows in retail's tables.
JUNK = re.compile(r"[\[(](PH|DND|DNT)[\])]|\bTEST\b|^zz|UNUSED|\(Old\)|^Blue Old God Fish Mount$", re.I)
SKILL_COMPANIONS = 778
F_EFFECT_MISC = 110  # Spell.dbc: the first effect's misc value, a companion spell's creature
COLUMNS = ("id", "kind", "retail_id", "name", "displays", "icon_fdid", "icon", "description")


def table(db2, name):
    path = os.path.join(db2, name + ".csv")
    if not os.path.exists(path):
        sys.exit("%s is missing: run the census (or wow-mod-retail-creatures' fetch.db2) first" % path)
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def clean(text):
    """Retail text as one plain line: no colour codes, links or line breaks."""
    text = re.sub(r"\|c[0-9a-fA-F]{8}|\|r|\|n|\|H[^|]*\|h|\|h|\|T[^|]*\|t", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def icon_names(listfile, fdids):
    """{file data id: icon name} for the wanted ids, from the community listfile."""
    names = {}
    with open(listfile, encoding="utf-8", errors="replace") as f:
        for line in f:
            fdid, _, path = line.rstrip("\n").partition(";")
            if fdid.isdigit() and int(fdid) in fdids and path.startswith("interface/icons/"):
                names[int(fdid)] = os.path.splitext(os.path.basename(path))[0].strip()
    return names


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--census", required=True)
    ap.add_argument("--db2", required=True)
    ap.add_argument("--listfile", required=True)
    ap.add_argument("--library", default=os.path.join(HERE, "..", "..", "mod-retail-library"))
    ap.add_argument("--spell-patch", required=True, help="the patch with the full Spell.dbc and SkillLineAbility.dbc")
    ap.add_argument("--taken", action="append", default=[], help="another module's look list (repeatable)")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    # What the client has already: every spell, and the creatures its companion spells summon.
    with tempfile.TemporaryDirectory() as tmp:
        dbc = {}
        for name in ("Spell", "SkillLineAbility"):
            dbc[name] = os.path.join(tmp, name + ".dbc")
            if not dbcmpq.extract(args.spell_patch, "DBFilesClient\\%s.dbc" % name, dbc[name]):
                sys.exit("%s has no %s.dbc" % (args.spell_patch, name))
        # Once the patch has the collection in it, its own rows are not "the client has it"
        # (some retail spell ids fall in the block and would hit them).
        spells = {r[0]: r for r in dbcmpq.read_dbc(dbc["Spell"])[0] if not BLOCK[0] <= r[0] <= BLOCK[1]}
        abilities = [a for a in dbcmpq.read_dbc(dbc["SkillLineAbility"])[0] if not BLOCK[0] <= a[0] <= BLOCK[1]]
    client_pets = {spells[a[2]][F_EFFECT_MISC] for a in abilities if a[1] == SKILL_COMPANIONS and a[2] in spells}

    looks = {}
    with open(os.path.join(args.library, "data", "looks.tsv"), encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            looks[int(r["retail_display"])] = int(r["display"])

    # Which library looks each retail mount and species wears, in the census's order.
    displays = {}
    with open(os.path.join(args.census, "displays.tsv"), encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            look = looks.get(int(r["retail_display"]))
            if look:
                wears = displays.setdefault((r["kind"], int(r["id"])), [])
                if look not in wears:
                    wears.append(look)

    # Looks another module already sells (its own display, or the library's for its retail display).
    taken = set()
    for path in args.taken:
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                if r.get("form") == "look":
                    continue
                taken.add(int(r["display"]))
                if r.get("retail_display"):
                    taken.add(LIBRARY_OFFSET + int(r["retail_display"]))

    capability = {int(c["ID"]): int(c["Flags"]) for c in table(args.db2, "MountCapability")}
    flies = set()
    for x in table(args.db2, "MountTypeXCapability"):
        if capability.get(int(x["MountCapabilityID"]), 0) & CAPABILITY_FLY:
            flies.add(int(x["MountTypeID"]))
    icons = {}
    for s in table(args.db2, "SpellMisc"):
        if s["DifficultyID"] == "0":
            icons[int(s["SpellID"])] = int(s["SpellIconFileDataID"])
    creatures = {int(c["ID"]): c["Name_lang"] for c in table(args.db2, "Creature")}

    rows, skipped = [], {}
    for m in table(args.db2, "Mount"):
        retail_id = int(m["ID"])
        wears = displays.get(("mount", retail_id))
        if not wears:
            continue
        name = clean(m["Name_lang"])
        if taken & set(wears):
            skipped.setdefault("another module sells it", []).append(name)
            continue
        if int(m["SourceSpellID"]) in spells:
            skipped.setdefault("the client has it (a new look of a stock mount)", []).append(name)
            continue
        if JUNK.search(name):
            skipped.setdefault("placeholder or test", []).append(name)
            continue
        mount_type = int(m["MountTypeID"])
        if mount_type == GHOST_TYPE:
            skipped.setdefault("ghost mount (only while dead)", []).append(name)
            continue
        if int(m["Flags"]) & MOUNT_FLAG_SELF:
            skipped.setdefault("self mount (the player becomes it)", []).append(name)
            continue
        kind = "flyer" if mount_type in flies and mount_type not in WATER_TYPES else "mount"
        rows.append(dict(id=MOUNT_BASE + retail_id, kind=kind, retail_id=retail_id, name=name, displays=wears,
                         icon_fdid=icons.get(int(m["SourceSpellID"]), 0), description=clean(m["Description_lang"])))
    for p in table(args.db2, "BattlePetSpecies"):
        retail_id = int(p["ID"])
        wears = displays.get(("pet", retail_id))
        if not wears:
            continue
        name = clean(creatures.get(int(p["CreatureID"]), ""))
        if taken & set(wears):
            skipped.setdefault("another module sells it", []).append(name)
            continue
        if int(p["CreatureID"]) in client_pets or int(p["SummonSpellID"]) in spells:
            skipped.setdefault("the client has it (a new look of a stock pet)", []).append(name)
            continue
        if not name or JUNK.search(name):
            skipped.setdefault("placeholder or test", []).append(name or "species %d" % retail_id)
            continue
        rows.append(dict(id=PET_BASE + retail_id, kind="pet", retail_id=retail_id, name=name, displays=wears,
                         icon_fdid=int(p["IconFileDataID"]), description=clean(p["Description_lang"])))

    # Two retail rows of one kind with the same name, one wearing only looks the other has (a
    # class mount's second copy, say): keep the first.
    kept = []
    for r in sorted(rows, key=lambda r: r["id"]):
        if any(k["kind"] == r["kind"] and k["name"] == r["name"] and set(r["displays"]) <= set(k["displays"])
               for k in kept):
            skipped.setdefault("a copy of another row (same name and looks)", []).append(r["name"])
            continue
        kept.append(r)
    rows = kept
    for r in rows:
        if len(r["displays"]) > MAX_LOOKS:
            skipped.setdefault("looks past the first %d dropped" % MAX_LOOKS, []).append(
                "%s (%d)" % (r["name"], len(r["displays"])))
            del r["displays"][MAX_LOOKS:]

    if any(r["id"] >= PET_BASE for r in rows if r["kind"] != "pet") or any(r["id"] >= PET_BASE + 10000 for r in rows):
        sys.exit("a retail id no longer fits its block (mounts 400000-409999, pets 410000-419999)")

    names = icon_names(args.listfile, {r["icon_fdid"] for r in rows})
    for r in rows:
        r["icon"] = names.get(r["icon_fdid"], "")
        if not r["icon"]:
            skipped.setdefault("no icon (uses the question mark)", []).append(r["name"])
            r["icon_fdid"] = 0

    rows.sort(key=lambda r: r["id"])
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        f.write("\t".join(COLUMNS) + "\n")
        for r in rows:
            r["displays"] = ",".join(str(d) for d in r["displays"])
            f.write("\t".join(str(r[c]).replace("\t", " ") for c in COLUMNS) + "\n")
    kinds = {k: sum(r["kind"] == k for r in rows) for k in ("mount", "flyer", "pet")}
    print("%s: %d rows (%s)" % (args.out, len(rows), ", ".join("%d %ss" % (n, k) for k, n in kinds.items())))
    for why, what in sorted(skipped.items()):
        print("  %s: %d (%s%s)" % (why, len(what), ", ".join(what[:6]), ", ..." if len(what) > 6 else ""))


if __name__ == "__main__":
    main()
