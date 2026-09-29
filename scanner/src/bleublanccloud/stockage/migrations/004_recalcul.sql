-- Migration 004 : recalcul des scores sans rescanner (bbcloud scores recalculer)

-- Date du dernier recalcul ayant modifié les constats ou le score d'un scan.
-- Les rapports IA rédigés avant cette date décrivent d'anciens constats : ils ne sont plus
-- publiés et seront régénérés (ou repris du cache) par « bbcloud rapports generer ».
ALTER TABLE scans ADD COLUMN recalcule_le TEXT;
