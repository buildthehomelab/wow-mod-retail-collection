-- acore_world. Run by hand to remove mod-retail-collection's rows: everything in its block
-- 400000-419999 (a mount's or pet's spell, item and creature share one id there).
-- Learned mounts and pets are lost for good: at the next login the core deletes every spell it no
-- longer knows from all characters (character_spell), and reinstalling doesn't bring them back.
-- Put the spell patch back to a build without the collection as well.
DELETE FROM `item_template` WHERE `entry` BETWEEN 400000 AND 419999;
DELETE FROM `spell_script_names` WHERE `spell_id` BETWEEN 400000 AND 419999;
DELETE FROM `skilllineability_dbc` WHERE `ID` BETWEEN 400000 AND 419999;
DELETE FROM `spell_dbc` WHERE `ID` BETWEEN 400000 AND 419999;
DELETE FROM `creature_template_model` WHERE `CreatureID` BETWEEN 400000 AND 419999;
DELETE FROM `creature_template` WHERE `entry` BETWEEN 400000 AND 419999;
