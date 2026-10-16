#!/usr/bin/env python3
"""Turn data/collection.tsv into mounts and companion pets: rows for the realm's spell patch and
the module's world database SQL.

    RETAIL_SOURCE=cdn python3 build_items.py --patch patch-z80-spells-and-items.MPQ \\
        --client /path/to/client --cache ~/retail-cache \\
        --out patch-z80-spells-and-items-new.MPQ --sql ../data/sql/db-world/mod_retail_collection.sql

--patch is the realm's patch that carries Spell.dbc, SkillLineAbility.dbc, Item.dbc,
ItemDisplayInfo.dbc and SpellIcon.dbc. A patch MPQ replaces whole files, so the new rows go into
its copies and every other file in it is copied unchanged. Per row of the collection it gains:

- Spell.dbc: the summon spell, a copy of Bombay Cat (10673) for a pet and of Amani War Bear
  (43688) for a mount: a mounted aura on the row's creature, +100% mounted speed, 1.5 s cast.
- SkillLineAbility.dbc: that spell on the Companions or the Mounts skill line, which puts it on
  the Pets or the Mounts tab (and makes mod-accountwide-mounts share it).
- Item.dbc and ItemDisplayInfo.dbc: the item that teaches it.
- SpellIcon.dbc: its icon, and the icon file when the client doesn't have one of that name (the
  HD client packs carry most of retail's icons already).

A row's id is its spell, item, creature, SkillLineAbility, SpellIcon and ItemDisplayInfo id.

A `flyer` is a mount that also flies where flying mounts can: the same ground mount spell, bound to
wow-mod-retail-pets' flyer script (spell_retail_pets_flyer), which adds flight by riding skill.
Without that module on the server a flyer is a ground mount, and the server logs that the script
is missing.

The creatures wear wow-mod-retail-library's looks (the `displays` column, at random when there are
several, like retail's breeds and faction colours), so the server needs that module and the client
its two patches.

The icons come from Blizzard's CDN (or wago.tools) through wow-mod-retail-creatures' fetch.py:
--creatures is that repo's checkout (default: next to this one). Running the tool again on its
own output changes nothing.
"""
import argparse
import csv
import ctypes
import glob
import os
import re
import struct
import sys
import tempfile

import dbcmpq
from dbcmpq import add_string, read_dbc, string_at, template, upsert, write_dbc

HERE = os.path.dirname(os.path.abspath(__file__))
COLLECTION = os.path.join(HERE, "..", "data", "collection.tsv")
BLOCK = (400000, 419999)  # mounts 400000 + retail mount id, pets 410000 + retail species id

TEMPLATE_ITEM_DISPLAY = 20629   # Cat Carrier (Bombay)'s display: an icon and nothing else
SPELL_LEARNING = 55884          # item spell 1 of every companion and mount item; teaches item spell 2
ITEM_SPELLTRIGGER_LEARN = 6
ITEM_CLASS_MISC = 15
SKILL_RIDING, RIDING_APPRENTICE = 762, 75
UNSET = 0xFFFFFFFF
FLYER_SCRIPT = "spell_retail_pets_flyer"

# What a row of each kind becomes (the same as wow-mod-retail-pets' pets and mounts):
#   spell     Spell.dbc row the summon spell copies: Bombay Cat and Amani War Bear
#   skill     Companions or Mounts
#   subclass  item subclass: pet or mount
#   item      (Flags, RequiredSkill, RequiredSkillRank, bonding, BagFamily, Quality) of the item
#   creature  (faction, unit_flags, type, movementId, flags_extra) of the creature
#   icon      the icon of a row retail gives none
#   text      the summon spell's description
KINDS = {
    "pet": dict(spell=10673, skill=778, subclass=2, item=(64, 0, 0, 0, 4096, 3),
                creature=(188, 768, 12, 121, 2), icon="INV_Box_PetCarrier_01",
                text="Right Click to summon and dismiss your %s."),
    "mount": dict(spell=43688, skill=777, subclass=5, item=(0, SKILL_RIDING, RIDING_APPRENTICE, 1, 0, 4),
                  creature=(35, 0, 1, 140, 0), icon="Ability_Mount_RidingHorse",
                  text="Summons and dismisses a rideable %s. This is a very fast mount."),
}
KINDS["flyer"] = dict(KINDS["mount"], text="Summons and dismisses a rideable %s. This mount can fly "
                      "where flying mounts can, faster with more Riding skill.")

SPELL_FIELDS = 234
F_EFFECT_MISC, F_ICON, F_ACTIVE_ICON, F_NAME, F_DESCRIPTION = 110, 133, 134, 136, 170
STRING_FIELDS = set(range(136, 152)) | set(range(153, 169)) | set(range(170, 186)) | set(range(187, 203))
FLOAT_FIELDS = {47, 77, 78, 79, 101, 102, 103, 119, 120, 121, 216, 217, 218, 229, 230, 231}
# Plain `int` columns of AC's spell_dbc; every other integer column is unsigned.
SIGNED_FIELDS = {0, 13, 15, 41, *range(52, 71), 74, 75, 76, 80, 81, 82, *range(110, 116), 224, 228}
DESCRIPTION_MAX = 255  # item_template.description
SQL_CHUNK = 500        # rows per INSERT


def load_collection(path):
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    for r in rows:
        for k in ("id", "retail_id", "icon_fdid"):
            r[k] = int(r[k])
        r["displays"] = [int(d) for d in r["displays"].split(",")]
        if not 1 <= len(r["displays"]) <= 4:
            sys.exit("%s: %s has %d looks; a creature has 1 to 4 (creature_template_model.Idx 0-3)"
                     % (path, r["name"], len(r["displays"])))
        if r["kind"] not in KINDS:
            sys.exit("%s: %s is a %s, not one of %s" % (path, r["name"], r["kind"], ", ".join(KINDS)))
        if not BLOCK[0] <= r["id"] <= BLOCK[1]:
            sys.exit("%s: %s has id %d, outside the module's block %d-%d" % (path, r["name"], r["id"], *BLOCK))
        r["k"] = KINDS[r["kind"]]
        r["icon"] = r["icon"] or r["k"]["icon"]
        if not r["icon_fdid"]:
            r["icon_fdid"] = 0
    if len({r["id"] for r in rows}) != len(rows):
        sys.exit("%s: two rows share an id" % path)
    return rows


def client_icons(client, locale, patch):
    """Lower-case names of every Interface\\Icons file in the client's MPQs and the input patch. The
    client's own copy of the patch being rebuilt is skipped: it may be an earlier build that has
    icons the input patch doesn't."""
    lib, H = dbcmpq.stormlib()
    names = set()
    mpqs = [m for m in glob.glob(os.path.join(client, "Data", "*.[Mm][Pp][Qq]"))
            + glob.glob(os.path.join(client, "Data", locale, "*.[Mm][Pp][Qq]"))
            if os.path.basename(m).lower() != os.path.basename(patch).lower()] + [patch]
    for mpq in mpqs:
        h = dbcmpq.open_mpq(lib, H, mpq)
        found = ctypes.create_string_buffer(2048)
        find = lib.SFileFindFirstFile(h, b"Interface\\Icons\\*", found, None)
        while find:
            name = found.value.decode("latin-1")
            if name.lower().startswith("interface\\icons\\"):
                names.add(os.path.splitext(name.split("\\")[-1])[0].lower())
            if not lib.SFileFindNextFile(find, found):
                lib.SFileFindClose(find)
                break
        lib.SFileCloseArchive(h)
    if not names:
        sys.exit("no icons found in %s: is it a client folder?" % client)
    return names


def icon_blp(data, fdid):
    """A retail icon for the 3.3.5a client: BLP2 as before, but retail keeps more flags in the
    "has mipmaps" byte than a 1, so it is set to what the file holds (more than one mip level)."""
    if data[:4] != b"BLP2" or struct.unpack_from("<I", data, 4)[0] != 1 or data[8] not in (1, 2, 3):
        sys.exit("icon %d is not a BLP2 file the 3.3.5a client reads" % fdid)
    offsets = struct.unpack_from("<16I", data, 20)
    out = bytearray(data)
    out[11] = 1 if sum(1 for o in offsets if o) > 1 else 0
    return bytes(out)


def patch_dbcs(files, rows, args, tmp):
    """Adds the rows and icons to the unpacked spell patch. Returns the new spell rows."""
    def dbc(table):
        return "DBFilesClient\\%s.dbc" % table

    for table in ("Spell", "SkillLineAbility", "Item", "ItemDisplayInfo", "SpellIcon"):
        if dbc(table) not in files:
            sys.exit("%s has no %s.dbc" % (args.patch, table))
    spells, spell_str, fields = read_dbc(files[dbc("Spell")])
    if fields != SPELL_FIELDS:
        sys.exit("Spell.dbc has %d fields, not %d" % (fields, SPELL_FIELDS))
    abilities, ability_str, ability_fields = read_dbc(files[dbc("SkillLineAbility")])
    items, item_str, item_fields = read_dbc(files[dbc("Item")])
    displays, display_str, display_fields = read_dbc(files[dbc("ItemDisplayInfo")])
    icons, icon_str, icon_fields = read_dbc(files[dbc("SpellIcon")])

    # The block is the module's: its rows are written again from the collection. A row the
    # collection no longer has goes, and the core then takes that spell from every character
    # who knew it, so say so loudly.
    ours = {r["id"] for r in rows}
    gone = sorted(old[0] for old in spells if BLOCK[0] <= old[0] <= BLOCK[1] and old[0] not in ours)
    if gone:
        print("WARNING: %d spells of an earlier build are no longer in the collection and are dropped: %s"
              % (len(gone), ", ".join("%d %s" % (i, string_at(spell_str, next(r for r in spells if r[0] == i)[F_NAME]))
                                       for i in gone)))

    have = client_icons(args.client, args.locale, args.patch)
    sys.path.insert(0, os.path.join(args.creatures, "tools"))
    import fetch  # wow-mod-retail-creatures

    spells[:] = [r for r in spells if not BLOCK[0] <= r[0] <= BLOCK[1]]
    abilities[:] = [r for r in abilities if not BLOCK[0] <= r[0] <= BLOCK[1]]
    items[:] = [r for r in items if not BLOCK[0] <= r[0] <= BLOCK[1]]
    displays[:] = [r for r in displays if not BLOCK[0] <= r[0] <= BLOCK[1]]
    icons[:] = [r for r in icons if not BLOCK[0] <= r[0] <= BLOCK[1]]
    templates = {k: template(spells, v["spell"], "Spell.dbc row") for k, v in KINDS.items()}
    item_display = template(displays, TEMPLATE_ITEM_DISPLAY, "ItemDisplayInfo.dbc row")

    new_spells, new_icons = [], 0
    for r in rows:
        spell = list(templates[r["kind"]])
        spell[0] = r["id"]
        spell[F_EFFECT_MISC] = r["id"]
        spell[F_ICON] = r["id"]
        spell[F_ACTIVE_ICON] = 0
        spell[F_NAME] = add_string(spell_str, r["name"])
        spell[F_DESCRIPTION] = add_string(spell_str, r["k"]["text"] % r["name"])
        spells.append(spell)
        new_spells.append(spell)

        abilities.append([r["id"], r["k"]["skill"], r["id"], 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0])
        items.append([r["id"], ITEM_CLASS_MISC, r["k"]["subclass"], UNSET, UNSET, r["id"], 0, 0])
        display = list(item_display)
        display[0] = r["id"]
        display[5] = add_string(display_str, r["icon"])
        displays.append(display)
        icons.append([r["id"], add_string(icon_str, "Interface\\Icons\\" + r["icon"])])

        name = "Interface\\Icons\\%s.blp" % r["icon"]
        if r["icon"].lower() not in have and name not in files:
            try:
                data = fetch.casc(args.cache, r["icon_fdid"])
            except (KeyError, RuntimeError, OSError) as e:  # not in the build, or a failed download
                sys.exit("%s: can't download its icon %d (%r)" % (r["name"], r["icon_fdid"], e))
            except Exception as e:
                if type(e).__name__ != "Encrypted":  # unreleased content (tact.Encrypted)
                    raise
                sys.exit("%s: its icon %d is encrypted (not released yet)" % (r["name"], r["icon_fdid"]))
            local = os.path.join(tmp, "icon-%d.blp" % r["icon_fdid"])
            with open(local, "wb") as f:
                f.write(icon_blp(data, r["icon_fdid"]))
            files[name] = local
            new_icons += 1

    write_dbc(files[dbc("Spell")], spells, spell_str, fields)
    write_dbc(files[dbc("SkillLineAbility")], abilities, ability_str, ability_fields)
    write_dbc(files[dbc("Item")], items, item_str, item_fields)
    write_dbc(files[dbc("ItemDisplayInfo")], displays, display_str, display_fields)
    write_dbc(files[dbc("SpellIcon")], icons, icon_str, icon_fields)
    print("%d icons added, %d already in the client" % (new_icons, len({r["icon"].lower() for r in rows} & have)))
    return new_spells


# --- SQL ---------------------------------------------------------------------------------------

def sql_str(s):
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def si(v):
    """A DBC uint32 as the signed int the server's *_dbc columns hold (-1, not 4294967295)."""
    return struct.unpack("<i", struct.pack("<I", v))[0]


def fl(v):
    return "%g" % struct.unpack("<f", struct.pack("<I", v))[0]


def short(text, limit=DESCRIPTION_MAX):
    """Retail lore cut to fit the item's description: whole sentences when it can."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[:end + 1] if end > limit // 3 else cut[:limit - 3].rstrip() + "..."


def inserts(f, head, lines):
    for i in range(0, len(lines), SQL_CHUNK):
        f.write(head + "\n" + ",\n".join(lines[i:i + SQL_CHUNK]) + ";\n")


def write_sql(path, rows, new_spells):
    def spell_value(i, v):
        if i in STRING_FIELDS:
            return "''"
        if i in FLOAT_FIELDS:
            return fl(v)
        return str(si(v) if i in SIGNED_FIELDS else v)

    first, last = BLOCK
    with open(path, "w", encoding="utf-8") as f:
        f.write("-- mod-retail-collection: every retail mount and companion pet that wow-mod-retail-library has a look\n")
        f.write("-- for, as a summon spell and the item that teaches it. Generated by tools/build_items.py from\n")
        f.write("-- data/collection.tsv: change that file and run the tool again, don't edit this one.\n")
        f.write("-- Ids %d-%d: a row's spell, item and creature share one id (mount 400000 + retail mount id,\n" % BLOCK)
        f.write("-- pet 410000 + retail battle pet species id). Nothing sells or drops the items yet.\n\n")

        f.write("-- The pets and the mounts' creatures, wearing the library's looks.\n")
        f.write("DELETE FROM `creature_template_model` WHERE `CreatureID` BETWEEN %d AND %d;\n" % BLOCK)
        f.write("DELETE FROM `creature_template` WHERE `entry` BETWEEN %d AND %d;\n" % BLOCK)
        inserts(f, "INSERT INTO `creature_template` (`entry`, `name`, `minlevel`, `maxlevel`, `faction`, `speed_walk`, `speed_run`, `BaseAttackTime`, `RangeAttackTime`, `unit_class`, `unit_flags`, `unit_flags2`, `type`, `movementId`, `flags_extra`) VALUES",
                ["(%d, %s, 1, 1, %d, 1, 1.14286, 2000, 2000, 1, %d, 2048, %d, %d, %d)" % (
                    r["id"], sql_str(r["name"]), *r["k"]["creature"]) for r in rows])
        inserts(f, "INSERT INTO `creature_template_model` (`CreatureID`, `Idx`, `CreatureDisplayID`, `DisplayScale`, `Probability`) VALUES",
                ["(%d, %d, %d, 1, 1)" % (r["id"], i, d) for r in rows for i, d in enumerate(r["displays"])])
        f.write("\n")

        f.write("-- Their summon spells (client: Spell.dbc in the spell patch), on the Companions and Mounts skill lines.\n")
        f.write("DELETE FROM `spell_dbc` WHERE `ID` BETWEEN %d AND %d;\n" % BLOCK)
        lines = []
        for r, row in zip(rows, new_spells):
            values = [spell_value(i, v) for i, v in enumerate(row)]
            values[F_NAME] = sql_str(r["name"])
            values[F_DESCRIPTION] = sql_str(r["k"]["text"] % r["name"])
            lines.append("(" + ", ".join(values) + ")")
        inserts(f, "INSERT INTO `spell_dbc` VALUES", lines)
        f.write("DELETE FROM `skilllineability_dbc` WHERE `ID` BETWEEN %d AND %d;\n" % BLOCK)
        inserts(f, "INSERT INTO `skilllineability_dbc` (`ID`, `SkillLine`, `Spell`, `RaceMask`, `ClassMask`, `ExcludeRace`, `ExcludeClass`, `MinSkillLineRank`, `SupercededBySpell`, `AcquireMethod`, `TrivialSkillLineRankHigh`, `TrivialSkillLineRankLow`, `CharacterPoints_1`, `CharacterPoints_2`) VALUES",
                ["(%d, %d, %d, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0)" % (r["id"], r["k"]["skill"], r["id"]) for r in rows])
        f.write("-- Flyers fly by wow-mod-retail-pets' script.\n")
        f.write("DELETE FROM `spell_script_names` WHERE `spell_id` BETWEEN %d AND %d;\n" % BLOCK)
        inserts(f, "INSERT INTO `spell_script_names` (`spell_id`, `ScriptName`) VALUES",
                ["(%d, %s)" % (r["id"], sql_str(FLYER_SCRIPT)) for r in rows if r["kind"] == "flyer"])
        f.write("\n")

        f.write("-- The items that teach them.\n")
        f.write("DELETE FROM `item_template` WHERE `entry` BETWEEN %d AND %d;\n" % BLOCK)
        lines = []
        for r in rows:
            flags, skill, rank, bonding, bag, quality = r["k"]["item"]
            lines.append("(%d, %d, %d, %s, %d, %d, %d, 0, 0, 20, %d, %d, 0, %d, -1, %d, %d, %d, %s, -1, %d)" % (
                r["id"], ITEM_CLASS_MISC, r["k"]["subclass"], sql_str(r["name"]), r["id"], quality, flags,
                skill, rank, SPELL_LEARNING, r["id"], ITEM_SPELLTRIGGER_LEARN, bonding,
                sql_str(short(r["description"])), bag))
        inserts(f, "INSERT INTO `item_template` (`entry`, `class`, `subclass`, `name`, `displayid`, `Quality`, `Flags`, `BuyPrice`, `SellPrice`, `ItemLevel`, `RequiredSkill`, `RequiredSkillRank`, `delay`, `spellid_1`, `spellcharges_1`, `spellid_2`, `spelltrigger_2`, `bonding`, `description`, `Material`, `BagFamily`) VALUES",
                lines)
    print("wrote", path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--patch", required=True, help="the realm's spell patch (Spell.dbc, Item.dbc, ...)")
    ap.add_argument("--client", required=True, help="the client folder (has Data/ and Data/<locale>/), for its icons")
    ap.add_argument("--locale", default="enUS")
    ap.add_argument("--cache", required=True, help="wow-mod-retail-creatures' download folder")
    ap.add_argument("--creatures", default=os.path.join(HERE, "..", "..", "mod-retail-creatures"),
                    help="wow-mod-retail-creatures checkout (for its downloader)")
    ap.add_argument("--collection", default=COLLECTION)
    ap.add_argument("--out", required=True, help="the new spell patch")
    ap.add_argument("--sql", help="write the module's world SQL here")
    args = ap.parse_args()

    rows = load_collection(args.collection)
    with tempfile.TemporaryDirectory() as tmp:
        files = dbcmpq.unpack(args.patch, tmp)
        new_spells = patch_dbcs(files, rows, args, tmp)
        dbcmpq.pack(args.out, [(local, name) for name, local in sorted(files.items())])
        print("%s: %d mounts and pets, %d files, %.1f MB" % (
            args.out, len(rows), len(files), os.path.getsize(args.out) / 1e6))
    if args.sql:
        # The SQL file is what the server has: warn about spells it had that this build drops too
        # (the check in patch_dbcs only sees the spells of an earlier build in --patch).
        if os.path.exists(args.sql):
            old = open(args.sql, encoding="utf-8").read()
            start = old.find("INSERT INTO `spell_dbc` VALUES")
            had = {int(m) for m in re.findall(r"^\((4[01]\d{4}),", old[start:], re.M)} if start >= 0 else set()
            gone = sorted(had - {r["id"] for r in rows})
            if gone:
                print("WARNING: %d spells in the current %s are not in this build: %s"
                      % (len(gone), os.path.basename(args.sql), ", ".join(map(str, gone))))
        write_sql(args.sql, rows, new_spells)


if __name__ == "__main__":
    main()
