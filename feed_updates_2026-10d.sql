-- Google News topic feeds, 2026-10-23: Reuters / Bloomberg / WSJ / FT / AP headlines without their APIs.
-- Feeds named "Google News: ..." credit each item to its real outlet in Delphi (see aggregator.fetch_feed).
-- Newsletter only: links are Google redirects, so research mode's page fetching can't use them.
-- Checked live 2026-10-23: ~100 items/feed/week, ~170/week total pass the keyword filter.
-- Run once in Supabase → SQL Editor. Safe to re-run.

BEGIN;

-- ("energy security" OR "power grid" OR "electricity prices") (site:reuters.com OR site:bloomberg.com OR site:wsj.com OR site:ft.com OR site:apnews.com)
INSERT INTO feed_sources (name, url, use_newsletter, use_research, tags, active, added_at) VALUES ('Google News: Energy Security', 'https://news.google.com/rss/search?q=%28%22energy+security%22+OR+%22power+grid%22+OR+%22electricity+prices%22%29+%28site%3Areuters.com+OR+site%3Abloomberg.com+OR+site%3Awsj.com+OR+site%3Aft.com+OR+site%3Aapnews.com%29+when%3A7d&hl=en-US&gl=US&ceid=US:en', true, false, 'policy,grid,markets', true, NOW()) ON CONFLICT (url) DO UPDATE SET use_newsletter = true, active = true;
-- (LNG OR "natural gas") (site:reuters.com OR site:bloomberg.com OR site:wsj.com OR site:ft.com OR site:apnews.com)
INSERT INTO feed_sources (name, url, use_newsletter, use_research, tags, active, added_at) VALUES ('Google News: LNG & Gas', 'https://news.google.com/rss/search?q=%28LNG+OR+%22natural+gas%22%29+%28site%3Areuters.com+OR+site%3Abloomberg.com+OR+site%3Awsj.com+OR+site%3Aft.com+OR+site%3Aapnews.com%29+when%3A7d&hl=en-US&gl=US&ceid=US:en', true, false, 'lng,hydrocarbons,markets', true, NOW()) ON CONFLICT (url) DO UPDATE SET use_newsletter = true, active = true;
-- (OPEC OR "oil prices" OR "crude oil") (site:reuters.com OR site:bloomberg.com OR site:wsj.com OR site:ft.com OR site:apnews.com)
INSERT INTO feed_sources (name, url, use_newsletter, use_research, tags, active, added_at) VALUES ('Google News: Oil', 'https://news.google.com/rss/search?q=%28OPEC+OR+%22oil+prices%22+OR+%22crude+oil%22%29+%28site%3Areuters.com+OR+site%3Abloomberg.com+OR+site%3Awsj.com+OR+site%3Aft.com+OR+site%3Aapnews.com%29+when%3A7d&hl=en-US&gl=US&ceid=US:en', true, false, 'hydrocarbons,markets', true, NOW()) ON CONFLICT (url) DO UPDATE SET use_newsletter = true, active = true;
-- ("nuclear reactor" OR uranium OR "small modular reactor") (site:reuters.com OR site:bloomberg.com OR site:wsj.com OR site:ft.com OR site:apnews.com)
INSERT INTO feed_sources (name, url, use_newsletter, use_research, tags, active, added_at) VALUES ('Google News: Nuclear', 'https://news.google.com/rss/search?q=%28%22nuclear+reactor%22+OR+uranium+OR+%22small+modular+reactor%22%29+%28site%3Areuters.com+OR+site%3Abloomberg.com+OR+site%3Awsj.com+OR+site%3Aft.com+OR+site%3Aapnews.com%29+when%3A7d&hl=en-US&gl=US&ceid=US:en', true, false, 'nuclear', true, NOW()) ON CONFLICT (url) DO UPDATE SET use_newsletter = true, active = true;
-- "data center" (power OR electricity OR grid) (site:reuters.com OR site:bloomberg.com OR site:wsj.com OR site:ft.com OR site:apnews.com)
INSERT INTO feed_sources (name, url, use_newsletter, use_research, tags, active, added_at) VALUES ('Google News: Data Centers', 'https://news.google.com/rss/search?q=%22data+center%22+%28power+OR+electricity+OR+grid%29+%28site%3Areuters.com+OR+site%3Abloomberg.com+OR+site%3Awsj.com+OR+site%3Aft.com+OR+site%3Aapnews.com%29+when%3A7d&hl=en-US&gl=US&ceid=US:en', true, false, 'ai_datacenters,grid', true, NOW()) ON CONFLICT (url) DO UPDATE SET use_newsletter = true, active = true;
-- ("Georgia Power" OR "Georgia Public Service Commission" OR "Plant Vogtle")
INSERT INTO feed_sources (name, url, use_newsletter, use_research, tags, active, added_at) VALUES ('Google News: Georgia Energy', 'https://news.google.com/rss/search?q=%28%22Georgia+Power%22+OR+%22Georgia+Public+Service+Commission%22+OR+%22Plant+Vogtle%22%29+when%3A7d&hl=en-US&gl=US&ceid=US:en', true, false, 'georgia,southeast', true, NOW()) ON CONFLICT (url) DO UPDATE SET use_newsletter = true, active = true;

COMMIT;

SELECT name, use_newsletter, active FROM feed_sources WHERE name LIKE 'Google News:%' ORDER BY name;
