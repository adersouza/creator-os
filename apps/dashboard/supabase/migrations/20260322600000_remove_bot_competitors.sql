-- Remove confirmed bot network from competitor tracking
-- These 5 accounts share Snap handles (emilitabeacon/emilitacrown/jessyemre/krisspini)
-- indicating they are the same bot farm. Feeding AI-generated bot content
-- back into our AI generation creates model collapse risk.
-- CASCADE will also delete their competitor_top_posts and competitor_snapshots.

DELETE FROM competitors WHERE username IN (
  'minaxxscarlet',
  'veexxdream',
  'nikoxnight',
  'eden.verse__',
  'sage.inmind'
);
