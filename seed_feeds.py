#!/usr/bin/env python3
"""
seed_feeds.py — One-time script to populate the feed_sources table in Supabase.

Run this ONCE after deploying to Render (or any time you want to re-seed):

    DATABASE_URL=<your-supabase-connection-string> python seed_feeds.py

The DATABASE_URL must be the Supabase PostgreSQL connection string, NOT sqlite.
Find it in: Render dashboard → Environment → DATABASE_URL
       or:  Supabase dashboard → Settings → Database → Connection string

Safe to run multiple times — uses INSERT ... ON CONFLICT DO NOTHING.
"""

import os
import sys

# ── Feed definitions ──────────────────────────────────────────────────────────
# Each entry: (name, url, use_newsletter, use_research, tags, notes)

NEWSLETTER_FEEDS = [
    # Geopolitics & General Energy
    ("Foreign Policy",          "https://foreignpolicy.com/feed/",                              True, True,  "policy,international,geopolitics", ""),
    ("War on the Rocks",        "https://warontherocks.com/feed/",                              True, True,  "policy,security,international",   ""),
    ("The Diplomat",            "https://thediplomat.com/feed/",                                True, True,  "policy,international,asia",       ""),
    ("Politico Energy",         "https://rss.politico.com/energy.xml",                          True, True,  "policy,government",               ""),
    ("The Hill Energy",         "https://thehill.com/tag/energy/feed/",                         True, True,  "policy,government",               ""),
    ("Breaking Defense",        "https://breakingdefense.com/feed/",                            True, True,  "security,policy",                 ""),
    ("Lawfare",                 "https://www.lawfaremedia.org/feed",                            True, True,  "policy,security,regulatory",      ""),
    # Renewables
    ("RenewableEnergyWorld",    "https://www.renewableenergyworld.com/feed/",                   True, True,  "renewables",                      ""),
    ("PV Magazine",             "https://www.pv-magazine.com/feed/",                            True, True,  "renewables,solar",                ""),
    ("CleanTechnica",           "https://cleantechnica.com/feed/",                              True, True,  "renewables,ev,technology",        ""),
    ("Offshore Wind Biz",       "https://www.offshorewind.biz/feed/",                           True, True,  "renewables,offshore_wind",        ""),
    ("Energy Storage News",     "https://www.energy-storage.news/feed/",                        True, True,  "renewables,storage,grid",         ""),
    ("Think GeoEnergy",         "https://www.thinkgeoenergy.com/feed/",                         True, True,  "renewables,geothermal",           ""),
    ("Grist Energy",            "https://grist.org/energy/feed/",                               True, True,  "renewables,policy,climate",       ""),
    # Nuclear
    ("World Nuclear News",      "https://www.world-nuclear-news.org/rss",                       True, True,  "nuclear",                         ""),
    ("Neutron Bytes",           "https://neutronbytes.com/feed/",                               True, True,  "nuclear",                         ""),
    ("ANS Nuclear Newswire",    "https://www.ans.org/news/feed/",                               True, True,  "nuclear",                         ""),
    # Hydrocarbons
    ("OilPrice.com",            "https://oilprice.com/rss/main",                                True, True,  "hydrocarbons,lng,markets",        ""),
    ("EIA Today in Energy",     "https://www.eia.gov/rss/todayinenergy.xml",                    True, True,  "hydrocarbons,government,markets", ""),
    ("Hart Energy",             "https://www.hartenergy.com/rss/news",                          True, True,  "hydrocarbons,lng",                ""),
    # Georgia & Southeast US
    ("The Current GA",          "https://thecurrentga.org/feed/",                               True, True,  "georgia,southeast",               ""),
    ("11Alive Atlanta",         "https://www.11alive.com/feeds/syndication/rss",                True, False, "georgia,southeast",               "Too broad for research"),
    ("WSB-TV Atlanta",          "https://www.wsbtv.com/news/topstory.rss",                      True, False, "georgia,southeast",               "Too broad for research"),
    # AI & Data Centers
    ("Data Center Dynamics",    "https://www.datacenterdynamics.com/en/rss/",                   True, True,  "data_centers,ai_infrastructure",  ""),
    ("Data Center Knowledge",   "https://www.datacenterknowledge.com/rss.xml",                  True, True,  "data_centers,ai_infrastructure",  ""),
    ("Data Center Post",        "https://datacenterpost.com/feed/",                             True, True,  "data_centers",                    ""),
]

RESEARCH_FEEDS = [
    # Nuclear & SMR
    ("NEI Nuclear Notes",           "https://www.nei.org/rss/news",                                         False, True, "nuclear,policy",               ""),
    ("IAEA Newscenter",             "https://www.iaea.org/feeds/topnews.xml",                               False, True, "nuclear,policy,international", ""),
    ("NRC News Releases",           "https://www.nrc.gov/reading-rm/doc-collections/news/rss.xml",          False, True, "nuclear,regulatory,government",""),
    ("Nuclear Engineering Intl",    "https://www.neimagazine.com/feed/",                                    False, True, "nuclear,technology",           ""),
    ("Third Way",                   "https://www.thirdway.org/feed",                                        False, True, "nuclear,policy,renewables",    ""),
    ("Power Magazine Nuclear",      "https://www.powermag.com/nuclear/feed/",                               False, True, "nuclear,technology",           ""),
    # LNG & Hydrocarbons
    ("LNG World News",              "https://www.lngworldnews.com/feed/",                                   False, True, "lng,hydrocarbons",             ""),
    ("Offshore Energy",             "https://www.offshore-energy.biz/feed/",                                False, True, "lng,hydrocarbons,offshore",    ""),
    ("Natural Gas Intelligence",    "https://www.naturalgasintel.com/feed/",                                False, True, "lng,hydrocarbons,markets",     "Partial paywall"),
    ("Oil & Gas Journal",           "https://www.ogj.com/rss",                                             False, True, "hydrocarbons,lng,technology",  ""),
    ("Rigzone",                     "https://www.rigzone.com/news/rss/rigzone_latest.aspx",                 False, True, "hydrocarbons,lng,offshore",    ""),
    # Data Centers & AI Infrastructure
    ("Data Center Frontier",        "https://www.datacenterfrontier.com/feed/",                             False, True, "data_centers,ai_infrastructure",""),
    ("Uptime Institute Blog",       "https://uptimeinstitute.com/resources/feed/",                          False, True, "data_centers,reliability",     ""),
    ("The Register Data Centre",    "https://www.theregister.com/data_centre/rss",                          False, True, "data_centers,technology",      ""),
    ("SDxCentral",                  "https://www.sdxcentral.com/feed/",                                     False, True, "data_centers,technology",      ""),
    # Grid, Transmission & Power
    ("Utility Dive",                "https://www.utilitydive.com/feeds/news/",                              False, True, "grid,utilities,policy",        ""),
    ("POWER Magazine",              "https://www.powermag.com/feed/",                                       False, True, "grid,power_generation",        ""),
    ("T&D World",                   "https://www.tdworld.com/rss/all",                                      False, True, "grid,transmission",            ""),
    ("RTO Insider",                 "https://www.rtoinsider.com/feed/",                                     False, True, "grid,regulatory,markets",      "May be paywalled"),
    ("Greentech Media",             "https://www.greentechmedia.com/rss/all",                               False, True, "grid,renewables,markets",      ""),
    # Policy & Think Tanks
    ("Brookings Institution",       "https://www.brookings.edu/feed/",                                      False, True, "policy,research",              ""),
    ("CSIS Analysis",               "https://www.csis.org/rss/analysis",                                   False, True, "policy,security,research",     ""),
    ("Atlantic Council",            "https://www.atlanticcouncil.org/feed/",                                False, True, "policy,security,international",""),
    ("Columbia SIPA Energy Policy", "https://www.energypolicy.columbia.edu/feed/",                          False, True, "policy,research,lng,renewables",""),
    ("Belfer Center",               "https://www.belfercenter.org/rss.xml",                                 False, True, "policy,security,nuclear",      ""),
    ("RAND Corporation",            "https://www.rand.org/pubs/rss/rss_feeds.xml",                          False, True, "policy,security,research",     ""),
    ("IEEFA",                       "https://ieefa.org/feed/",                                              False, True, "policy,research,energy_finance",""),
    ("Rocky Mountain Institute",    "https://rmi.org/feed/",                                                False, True, "policy,renewables,research",   ""),
    ("Wilson Center",               "https://www.wilsoncenter.org/rss.xml",                                 False, True, "policy,security,international",""),
    ("Carbon Brief",                "https://www.carbonbrief.org/feed",                                     False, True, "policy,climate,research",      ""),
    ("Energy Monitor",              "https://www.energymonitor.ai/feed/",                                   False, True, "policy,markets,international", ""),
    # Government & Regulatory
    ("DOE News",                    "https://www.energy.gov/rss.xml",                                       False, True, "government,policy",            ""),
    ("FERC News",                   "https://www.ferc.gov/rss/news.rss",                                    False, True, "regulatory,grid,lng",          "URL may need verification"),
    ("EPA Climate News",            "https://www.epa.gov/newsreleases/search/rss/topic/climate-change",     False, True, "regulatory,government,policy", ""),
    # Regional & Southeast
    ("Georgia Recorder",            "https://georgiarecorder.com/feed/",                                    False, True, "georgia,southeast,policy",     ""),
    ("Energy News Network",         "https://energynews.us/feed/",                                          False, True, "southeast,policy,renewables",  ""),
    ("Southeast Energy News",       "https://southeastenergynews.com/feed/",                                False, True, "southeast,grid,utilities",     "URL may need verification"),
    ("Inside Climate News",         "https://insideclimatenews.org/feed/",                                  False, True, "policy,climate,southeast",     ""),
]


def main():
    db_url = os.environ.get("DATABASE_URL", "")

    if not db_url:
        # Try loading from .env
        try:
            from dotenv import load_dotenv
            load_dotenv()
            db_url = os.environ.get("DATABASE_URL", "")
        except ImportError:
            pass

    if not db_url:
        print("ERROR: DATABASE_URL not set.")
        print("Run as: DATABASE_URL=<supabase-url> python seed_feeds.py")
        sys.exit(1)

    if db_url.startswith("sqlite"):
        print("ERROR: DATABASE_URL points to SQLite — this script requires the Supabase connection string.")
        print("Find it in Render dashboard → Environment → DATABASE_URL")
        sys.exit(1)

    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
        sys.exit(1)

    print(f"Connecting to Supabase...")
    conn = psycopg2.connect(db_url)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            # Create table if it doesn't exist
            cur.execute("""
                CREATE TABLE IF NOT EXISTS feed_sources (
                    id              SERIAL PRIMARY KEY,
                    name            TEXT NOT NULL,
                    url             TEXT NOT NULL UNIQUE,
                    use_newsletter  BOOLEAN NOT NULL DEFAULT TRUE,
                    use_research    BOOLEAN NOT NULL DEFAULT TRUE,
                    tags            TEXT NOT NULL DEFAULT '',
                    active          BOOLEAN NOT NULL DEFAULT TRUE,
                    notes           TEXT NOT NULL DEFAULT '',
                    added_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            all_feeds = [
                (name, url, use_nl, use_res, tags, notes)
                for (name, url, use_nl, use_res, tags, notes) in NEWSLETTER_FEEDS + RESEARCH_FEEDS
            ]

            inserted = 0
            skipped = 0
            for name, url, use_nl, use_res, tags, notes in all_feeds:
                cur.execute("""
                    INSERT INTO feed_sources (name, url, use_newsletter, use_research, tags, notes)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (url) DO NOTHING
                """, (name, url, use_nl, use_res, tags, notes))
                if cur.rowcount:
                    inserted += 1
                    print(f"  + {name}")
                else:
                    skipped += 1

            conn.commit()
            print(f"\nDone: {inserted} feeds inserted, {skipped} already existed.")
            print(f"Total in feed_sources: {inserted + skipped} feeds")

    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
