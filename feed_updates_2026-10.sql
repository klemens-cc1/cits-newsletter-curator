-- Feed source update, 2026-10-23: more newsletter source diversity.
-- Every URL below was checked live on 2026-10-23 with the aggregator's own user agent.
-- Run once in Supabase → SQL Editor. Safe to re-run.

BEGIN;

-- 1. Existing research-only feeds that are live and on-topic → also use for the newsletter
UPDATE feed_sources SET use_newsletter = true, active = true WHERE url = 'https://www.utilitydive.com/feeds/news/';  -- Utility Dive
UPDATE feed_sources SET use_newsletter = true, active = true WHERE url = 'https://www.powermag.com/feed/';  -- POWER Magazine
UPDATE feed_sources SET use_newsletter = true, active = true WHERE url = 'https://www.rtoinsider.com/feed/';  -- RTO Insider
UPDATE feed_sources SET use_newsletter = true, active = true WHERE url = 'https://www.carbonbrief.org/feed';  -- Carbon Brief
UPDATE feed_sources SET use_newsletter = true, active = true WHERE url = 'https://www.energymonitor.ai/feed/';  -- Energy Monitor
UPDATE feed_sources SET use_newsletter = true, active = true WHERE url = 'https://georgiarecorder.com/feed/';  -- Georgia Recorder
UPDATE feed_sources SET use_newsletter = true, active = true WHERE url = 'https://insideclimatenews.org/feed/';  -- Inside Climate News
UPDATE feed_sources SET use_newsletter = true, active = true WHERE url = 'https://www.naturalgasintel.com/feed/';  -- Natural Gas Intelligence
UPDATE feed_sources SET use_newsletter = true, active = true WHERE url = 'https://www.rigzone.com/news/rss/rigzone_latest.aspx';  -- Rigzone

-- 2. Feeds whose old URL is dead → working URL (Google News site: search where the site has no RSS)
UPDATE feed_sources SET url = 'https://ieefa.org/rss.xml', use_newsletter = true, active = true WHERE url = 'https://ieefa.org/feed/';  -- IEEFA
UPDATE feed_sources SET url = 'https://news.google.com/rss/search?q=site:csis.org+energy+when:7d&hl=en-US&gl=US&ceid=US:en', use_newsletter = true, active = true WHERE url = 'https://www.csis.org/rss/analysis';  -- CSIS Analysis
UPDATE feed_sources SET url = 'https://news.google.com/rss/search?q=site:energypolicy.columbia.edu+when:7d&hl=en-US&gl=US&ceid=US:en', use_newsletter = true, active = true WHERE url = 'https://www.energypolicy.columbia.edu/feed/';  -- Columbia SIPA Energy Policy
UPDATE feed_sources SET url = 'https://news.google.com/rss/search?q=site:brookings.edu+energy+when:7d&hl=en-US&gl=US&ceid=US:en', use_newsletter = true, active = true WHERE url = 'https://www.brookings.edu/feed/';  -- Brookings Institution
UPDATE feed_sources SET url = 'https://news.google.com/rss/search?q=site:rand.org+energy+when:7d&hl=en-US&gl=US&ceid=US:en', use_newsletter = true, active = true WHERE url = 'https://www.rand.org/pubs/rss/rss_feeds.xml';  -- RAND Corporation
UPDATE feed_sources SET url = 'https://news.google.com/rss/search?q=site:ferc.gov+when:7d&hl=en-US&gl=US&ceid=US:en', use_newsletter = true, active = true WHERE url = 'https://www.ferc.gov/rss/news.rss';  -- FERC News

-- 3. New sources (newsletter + research)
INSERT INTO feed_sources (name, url, use_newsletter, use_research, tags, active, added_at) VALUES ('Canary Media', 'https://www.canarymedia.com/rss', true, true, 'grid,renewables,policy', true, NOW()) ON CONFLICT (url) DO UPDATE SET use_newsletter = true, active = true;
INSERT INTO feed_sources (name, url, use_newsletter, use_research, tags, active, added_at) VALUES ('Latitude Media', 'https://www.latitudemedia.com/feed', true, true, 'grid,ai_datacenters,markets', true, NOW()) ON CONFLICT (url) DO UPDATE SET use_newsletter = true, active = true;
INSERT INTO feed_sources (name, url, use_newsletter, use_research, tags, active, added_at) VALUES ('Heatmap', 'https://heatmap.news/feeds/feed.rss', true, true, 'policy,climate,renewables', true, NOW()) ON CONFLICT (url) DO UPDATE SET use_newsletter = true, active = true;
INSERT INTO feed_sources (name, url, use_newsletter, use_research, tags, active, added_at) VALUES ('Oxford Institute for Energy Studies', 'https://www.oxfordenergy.org/publications/feed/', true, true, 'research,international,lng,hydrocarbons', true, NOW()) ON CONFLICT (url) DO UPDATE SET use_newsletter = true, active = true;
INSERT INTO feed_sources (name, url, use_newsletter, use_research, tags, active, added_at) VALUES ('GPB News', 'https://www.gpb.org/rss.xml', true, true, 'georgia,southeast', true, NOW()) ON CONFLICT (url) DO UPDATE SET use_newsletter = true, active = true;
INSERT INTO feed_sources (name, url, use_newsletter, use_research, tags, active, added_at) VALUES ('Federal Register: DOE/FERC/NRC rules', 'https://www.federalregister.gov/api/v1/documents.rss?conditions%5Bagencies%5D%5B%5D=energy-department&conditions%5Bagencies%5D%5B%5D=federal-energy-regulatory-commission&conditions%5Bagencies%5D%5B%5D=nuclear-regulatory-commission&conditions%5Btype%5D%5B%5D=RULE&conditions%5Btype%5D%5B%5D=PRORULE', true, true, 'regulatory,government', true, NOW()) ON CONFLICT (url) DO UPDATE SET use_newsletter = true, active = true;
INSERT INTO feed_sources (name, url, use_newsletter, use_research, tags, active, added_at) VALUES ('Atlantic Council EnergySource', 'https://www.atlanticcouncil.org/category/blogs/energysource/feed/', true, true, 'policy,international,research', true, NOW()) ON CONFLICT (url) DO UPDATE SET use_newsletter = true, active = true;
INSERT INTO feed_sources (name, url, use_newsletter, use_research, tags, active, added_at) VALUES ('IEA', 'https://news.google.com/rss/search?q=site:iea.org+when:7d&hl=en-US&gl=US&ceid=US:en', true, true, 'international,research,markets', true, NOW()) ON CONFLICT (url) DO UPDATE SET use_newsletter = true, active = true;

-- 4. Dead or abandoned feeds (404 / empty / no posts in 3+ years) → deactivate (also stops research mode wasting time on them)
UPDATE feed_sources SET active = false WHERE url = 'https://www.tdworld.com/rss/all';  -- T&D World
UPDATE feed_sources SET active = false WHERE url = 'https://www.belfercenter.org/rss.xml';  -- Belfer Center
UPDATE feed_sources SET active = false WHERE url = 'https://www.wilsoncenter.org/rss.xml';  -- Wilson Center
UPDATE feed_sources SET active = false WHERE url = 'https://www.energy.gov/rss.xml';  -- DOE News
UPDATE feed_sources SET active = false WHERE url = 'https://energynews.us/feed/';  -- Energy News Network
UPDATE feed_sources SET active = false WHERE url = 'https://southeastenergynews.com/feed/';  -- Southeast Energy News
UPDATE feed_sources SET active = false WHERE url = 'https://www.nei.org/rss/news';  -- NEI Nuclear Notes
UPDATE feed_sources SET active = false WHERE url = 'https://www.iaea.org/feeds/topnews.xml';  -- IAEA Newscenter
UPDATE feed_sources SET active = false WHERE url = 'https://www.lngworldnews.com/feed/';  -- LNG World News
UPDATE feed_sources SET active = false WHERE url = 'https://www.ogj.com/rss';  -- Oil & Gas Journal
UPDATE feed_sources SET active = false WHERE url = 'https://rmi.org/feed/';  -- Rocky Mountain Institute

COMMIT;

-- Check:
SELECT name, use_newsletter, use_research, active FROM feed_sources ORDER BY active DESC, use_newsletter DESC, name;
