/*
 * mod-retail-collection loader.
 *
 * The module is data only: world database rows (data/sql/db-world) for the mounts' and pets'
 * spells, items and creatures, which the client knows from the spell patch. AzerothCore still
 * calls a loader for every module folder, so this one is empty.
 *
 * AzerothCore looks up a loader symbol derived from the module's folder name: for folder
 * "mod-retail-collection" that symbol is exactly "Addmod_retail_collectionScripts". If you clone the
 * repo under a different folder name, rename this function to match.
 *
 * Released under the MIT License.
 */

void Addmod_retail_collectionScripts()
{
}
