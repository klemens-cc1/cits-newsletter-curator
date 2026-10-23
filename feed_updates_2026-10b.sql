-- Follow-up to feed_updates_2026-10.sql, 2026-10-23.
-- The original 38 feeds had active = NULL. Both the aggregator and research mode only load active = true,
-- so they were never used (the aggregator silently fell back to feeds.yaml), and after the first
-- update only the 23 new rows would load. This activates the live ones and fixes or retires the rest.
-- Every URL below was checked live on 2026-10-23. Run once in Supabase → SQL Editor. Safe to re-run.

BEGIN;

-- 1. Dead URL → working URL (Google News site: search where the site blocks or dropped RSS)
UPDATE feed_sources SET url = 'https://www.11alive.com/feeds/syndication/rss/news', active = true WHERE url = 'https://www.11alive.com/feeds/syndication/rss';  -- 11Alive Atlanta
UPDATE feed_sources SET url = 'https://www.wsbtv.com/arc/outboundfeeds/rss/?outputType=xml', active = true WHERE url = 'https://www.wsbtv.com/news/topstory.rss';  -- WSB-TV Atlanta
UPDATE feed_sources SET url = 'https://www.lawfaremedia.org/feeds/articles', active = true WHERE url = 'https://www.lawfaremedia.org/feed';  -- Lawfare
UPDATE feed_sources SET url = 'https://thehill.com/policy/energy-environment/feed/', active = true WHERE url = 'https://thehill.com/tag/energy/feed/';  -- The Hill Energy
UPDATE feed_sources SET url = 'https://news.google.com/rss/search?q=site:hartenergy.com+when:7d&hl=en-US&gl=US&ceid=US:en', active = true WHERE url = 'https://www.hartenergy.com/rss/news';  -- Hart Energy
UPDATE feed_sources SET url = 'https://news.google.com/rss/search?q=site:nrc.gov+when:7d&hl=en-US&gl=US&ceid=US:en', active = true WHERE url = 'https://www.nrc.gov/reading-rm/doc-collections/news/rss.xml';  -- NRC News Releases
UPDATE feed_sources SET url = 'https://news.google.com/rss/search?q=site:datacenterfrontier.com+when:7d&hl=en-US&gl=US&ceid=US:en', active = true WHERE url = 'https://www.datacenterfrontier.com/feed/';  -- Data Center Frontier
UPDATE feed_sources SET url = 'https://journal.uptimeinstitute.com/feed/', active = true WHERE url = 'https://uptimeinstitute.com/resources/feed/';  -- Uptime Institute Blog

-- 2. Dead with no working alternative → deactivate
UPDATE feed_sources SET active = false WHERE url = 'https://www.greentechmedia.com/rss/all';  -- Greentech Media
UPDATE feed_sources SET active = false WHERE url = 'https://www.epa.gov/newsreleases/search/rss/topic/climate-change';  -- EPA Climate News
UPDATE feed_sources SET active = false WHERE url = 'https://www.powermag.com/nuclear/feed/';  -- Power Magazine Nuclear
UPDATE feed_sources SET active = false WHERE url = 'https://www.sdxcentral.com/feed/';  -- SDxCentral
UPDATE feed_sources SET active = false WHERE url = 'https://www.theregister.com/data_centre/rss';  -- The Register Data Centre
UPDATE feed_sources SET active = false WHERE url = 'https://www.thirdway.org/feed';  -- Third Way
UPDATE feed_sources SET active = false WHERE url = 'https://www.neimagazine.com/feed/';  -- Nuclear Engineering Intl

-- 3. Everything still NULL was checked live → activate
UPDATE feed_sources SET active = true WHERE active IS NULL;

-- 4. New rows inserted without the column default true → stop that recurring
ALTER TABLE feed_sources ALTER COLUMN active SET DEFAULT true;

COMMIT;

-- Check: expect no NULLs
SELECT name, use_newsletter, use_research, active FROM feed_sources ORDER BY active DESC NULLS FIRST, use_newsletter DESC, name;
