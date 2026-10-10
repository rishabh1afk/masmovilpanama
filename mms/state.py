"""Incremental-refresh state, read from data/masmovil.db (no network, no Apify).

Per channel we derive *watermarks* from rows already stored in the `items` table:
  - known ids (anything already stored is skipped -> never re-analysed),
  - newest stored date per kind (owned posts / mentions / reviews / comments),
  - the post-level comment counter stored with each post (seed for posts pulled before incremental mode).
Plus a small `fetch_state` table: the post-level comment counter we saw the last time we fetched
comments for a post, so a post's comments are only re-pulled when that counter has grown."""
import sqlite3, datetime as dt
from . import config as C

UTC = dt.timezone.utc


def ensure_fetch_state(con):
    con.execute("""CREATE TABLE IF NOT EXISTS fetch_state (channel TEXT, post_url TEXT, comments_seen INT,
                   checked_at TEXT, PRIMARY KEY (channel, post_url))""")


def _has_items(con):
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='items'").fetchone())


class Watermark:
    """Everything the collectors need to fetch only what's new for one channel."""

    def __init__(self, channel, ids=(), latest=None, latest_comment=None, post_counters=None, comments_seen=None):
        self.channel = channel
        self.ids = set(ids)
        self.latest = latest                    # newest non-comment item date (ISO) or None
        self.latest_comment = latest_comment    # newest comment date (ISO) or None
        self.post_counters = post_counters or {}   # post url -> comment counter stored with the post row
        self.comments_seen = comments_seen or {}   # post url -> post comment counter at last comment fetch

    @property
    def empty(self):
        return not self.ids

    def is_new(self, item_id):
        return item_id not in self.ids

    def since(self, overlap_days=1, recheck_days=0, kind="post"):
        """Datetime to fetch from: newest stored date minus an overlap (date-granular actor filters), and
        at least `recheck_days` back (to re-read comment counters on recent posts). Never older than
        LOOKBACK_DAYS; an empty channel gets the full LOOKBACK_DAYS window."""
        now = dt.datetime.now(UTC)
        floor = now - dt.timedelta(days=C.LOOKBACK_DAYS)
        last = self.latest_comment if kind == "comment" else self.latest
        if not last:
            return floor
        d = dt.datetime.fromisoformat(last) - dt.timedelta(days=overlap_days)
        if recheck_days:
            d = min(d, now - dt.timedelta(days=recheck_days))
        return max(d, floor)

    def seen_count(self, post_url):
        """Comment counter at our last comment pull for this post (fetch_state), else the counter stored with
        the post row (posts pulled before incremental mode had their comments pulled in that same run),
        else 0 (a post we've never seen)."""
        if post_url in self.comments_seen:
            return int(self.comments_seen[post_url] or 0)
        return int(self.post_counters.get(post_url) or 0)

    def comments_wanted(self, post_url, post_comment_count):
        """True if the post's public comment counter grew since we last pulled its comments."""
        return int(post_comment_count or 0) > self.seen_count(post_url)


def load(channel, full=False, db_path=None):
    """Watermark for a channel. full=True ignores dates/counters (full LOOKBACK_DAYS re-pull) but still
    reports known ids, so stored items are skipped and only new ones are analysed."""
    p = db_path or C.DB_PATH
    if not p.exists():
        return Watermark(channel)
    con = sqlite3.connect(p)
    try:
        if not _has_items(con):
            return Watermark(channel)
        ids = [r[0] for r in con.execute("SELECT id FROM items WHERE channel=?", (channel,))]
        if full:
            return Watermark(channel, ids)
        latest = con.execute("SELECT max(date) FROM items WHERE channel=? AND kind!='comment'", (channel,)).fetchone()[0]
        latest_c = con.execute("SELECT max(date) FROM items WHERE channel=? AND kind='comment'", (channel,)).fetchone()[0]
        counters = dict(con.execute("""SELECT url, max(comments) FROM items WHERE channel=? AND kind!='comment'
                                       AND url IS NOT NULL GROUP BY url""", (channel,)).fetchall())
        seen = {}
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fetch_state'").fetchone():
            seen = dict(con.execute("SELECT post_url, comments_seen FROM fetch_state WHERE channel=?", (channel,)).fetchall())
        return Watermark(channel, ids, latest, latest_c, counters, seen)
    finally:
        con.close()
