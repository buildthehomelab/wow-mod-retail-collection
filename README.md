# Retail Collection

Every retail mount, and every retail battle pet that
[wow-mod-retail-library](https://github.com/buildthehomelab/wow-mod-retail-library) has a look
for, as something a player of an [AzerothCore](https://www.azerothcore.org/) (WotLK 3.3.5a) server
can own: a summon spell on the Mounts or Pets tab and the item that teaches it. 3,025 of them:
1,360 mounts (689 of them fly) and 1,665 companion pets.

- **A row's spell, item and creature share one id.** A mount is 400000 + its retail mount id, a pet
  410000 + its retail battle pet species id. The Chaos-Forged Gryphon is retail mount 2304, so
  it is spell, item and creature 402304 here: `.additem 402304`.
- [`data/collection.tsv`](data/collection.tsv) lists them: id, kind, retail id, name, the
  library looks the creature wears, the icon, and retail's lore text (the item's description).
- **This module doesn't sell or drop the items.** It makes them exist; where players get them
  (vendors, drops, achievements, a shop) is for other modules. Archaeology's rare rewards already
  hand out the Fossilized Raptor and Fossilized Hatchling; until a module covers the rest, a GM
  hands them out.

## How they work

- **Mounts** are ground mounts like the stock epic ones: +100% speed, usable with Apprentice
  Riding, and the stock mount speed rules of your server apply (a mod that scales mount speed by
  level scales these too). They are on the Mounts skill line, so a module that shares mounts
  across an account shares these.
- **Flyers** are the same ground mount, bound to
  [wow-mod-retail-pets](https://github.com/buildthehomelab/wow-mod-retail-pets)' flyer script: with
  Expert or Artisan Riding they fly where flying mounts can, like retail's mounts. Without that
  module on the server they stay on the ground (and the server logs that the script is missing).
- **Pets** are companions like the stock ones, summoned from the Pets tab.
- **Several looks:** a retail mount or pet with more than one look (faction colours, a pet's
  breeds, seasonal coats) is one spell here, and its creature wears one of them at random each
  time it is summoned. A creature takes at most four looks, so the three mounts with more keep
  retail's first four.
- **Every retail mount is its own mount**, whatever model it has: the Swift Albino Raptor, on a
  model the client already has, and the four Primal Raptors, new textures on a client model, are
  mounts of their own like the rest. Their looks are converted into the library too:
  [`data/wanted-looks.tsv`](data/wanted-looks.tsv) lists the mounts' looks the library still
  lacks, and is empty once it has them all.
- **Left out:** placeholder and test rows in retail's tables; the mounts the client already has
  (retail's spell is on the client's Mounts skill line: a stock mount whose look retail redrew,
  like the Charger, stays the stock one) and the pets it has; anything another module already
  sells (the build takes that module's look list, see Building); retail's ghost mounts (only for
  the dead) and "self mounts" that turn the player into the creature (a mount can't do that
  here); and a second row with the same name and looks as another (a class hall's copy of the
  Great Sunwalker Kodo, a skyriding drake's plain twin). Looks are the same when model and
  textures are, whatever the display.
- **Rows never go.** A mount or pet the list has keeps its row in later builds, even when another
  module starts selling it: the build stops rather than drop one.
- **Don't drop rows once players have them.** The core deletes a spell it no longer knows from
  every character at login, so a mount removed from the list (or the module uninstalled) is gone
  for good. The build warns when a rebuild drops one (compared with the input patch and with the
  module's current SQL).

## Installing

Server: clone this repo into the server's `modules` folder under the name `mod-retail-collection`
(AzerothCore names the module's loader after its folder), with
[wow-mod-retail-library](https://github.com/buildthehomelab/wow-mod-retail-library) next to it,
then rebuild:

```bash
cd modules
git clone https://github.com/buildthehomelab/wow-mod-retail-collection.git mod-retail-collection
```

The module has no code of its own; its SQL
([`data/sql/db-world`](data/sql/db-world/mod_retail_collection.sql)) adds the creatures, spells,
skill line rows and items.

Client: the spell patch (whichever patch of yours carries `Spell.dbc`, `Item.dbc`,
`SkillLineAbility.dbc`, `ItemDisplayInfo.dbc` and `SpellIcon.dbc`), rebuilt with the collection's
rows and about 200 icons the HD client packs don't have, plus wow-mod-retail-library's two
patches for the models. A player without them sees an empty spell or a question mark.

## Requirements

- An AzerothCore (WotLK 3.3.5a) server.
- [wow-mod-retail-library](https://github.com/buildthehomelab/wow-mod-retail-library): the looks.
- [wow-mod-retail-pets](https://github.com/buildthehomelab/wow-mod-retail-pets), for flyers to fly.
- To build: Python 3.10+, [StormLib](https://github.com/ladislav-zezula/StormLib), and
  [wow-mod-retail-creatures](https://github.com/buildthehomelab/wow-mod-retail-creatures) (its
  census and its downloader).

## Building

With wow-mod-retail-creatures, wow-mod-retail-library and wow-mod-retail-pets cloned next to this
repo under their module names (`mod-retail-creatures`, `mod-retail-library`, `mod-retail-pets`;
`--creatures` and `--library` take other paths), and the same census the library's look list came
from:

```bash
# the list: one row per retail mount, and per pet the library has a look for; the mounts' looks
# the library lacks go to data/wanted-looks.tsv (give it to the census and the library's
# inventory with --also, rebuild the library, and run this again)
python3 tools/collection.py --census <census dir> --db2 ~/retail-cache/db2 \
    --listfile ~/retail-cache/community-listfile.csv --spell-patch <your spell patch> \
    --taken ../mod-retail-pets/data/pets.tsv
# the spell patch and the SQL
RETAIL_SOURCE=cdn python3 tools/build_items.py --patch <your spell patch> --client <WoW folder> \
    --cache ~/retail-cache --out <new spell patch> --sql data/sql/db-world/mod_retail_collection.sql
```

`--db2` needs Mount, MountCapability, MountTypeXCapability, SpellMisc, BattlePetSpecies and
Creature from wago.tools (the census fetches most of them; wow-mod-retail-creatures'
`fetch.db2` gets the rest). `--client` is only read for its icons; it skips the client's own copy
of the patch being rebuilt (same file name as `--patch`), so keep that name, or an older build's
icons count as already there. The build only adds rows in 400000-419999 to the five tables and
leaves every other row and file alone; running it again on its own output changes nothing.

## Removing

Run [`data/sql/uninstall/mod_retail_collection_uninstall.sql`](data/sql/uninstall/mod_retail_collection_uninstall.sql)
on the world database, remove the module folder, rebuild, and go back to a spell patch without
the collection.

## Patch Notes: Retail Collection

Category: Collections

- 1,240 mounts and 1,665 companion pets from later expansions are now in the game as items that
  teach them. 634 of the mounts fly where flying mounts can once you have Expert Riding. Most of
  them can't be found yet: they will come from achievements, vendors and other sources in later
  updates.
- 120 more mounts join them, so nearly every retail mount the game didn't have is now its own mount:
  the Primal Raptors, Swift Albino Raptor and Skullripper, the Tauralus herd, the dragonriding
  drakes, the Delver's airships, the Headless Horseman's chargers, and more.

## Credits

- Mount and pet names and lore text (in `data/`): Blizzard Entertainment, from retail's tables.
  Icons: Blizzard Entertainment, downloaded from their CDN at build time and not stored here.
- Built on wow-mod-retail-library's looks and wow-mod-retail-pets' mount and pet rows.

## License

MIT, see [LICENSE](LICENSE).
