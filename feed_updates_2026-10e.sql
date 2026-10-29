-- Oxford Institute for Energy Studies, 2026-10-28: its RSS returns malformed XML to GitHub Actions
-- (works from home IPs, so likely bot-blocked). Switch to a Google News site: feed scoped to publications.
-- Run once in Supabase → SQL Editor. Safe to re-run.
UPDATE feed_sources SET url = 'https://news.google.com/rss/search?q=site:oxfordenergy.org/publications+when:7d&hl=en-US&gl=US&ceid=US:en', use_newsletter = true, active = true WHERE url = 'https://www.oxfordenergy.org/publications/feed/';  -- Oxford Institute for Energy Studies

SELECT name, url, active FROM feed_sources WHERE name = 'Oxford Institute for Energy Studies';
