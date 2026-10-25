import datetime
import unittest
from unittest.mock import patch

import server


DID = "did:plc:partner2345"
OTHER_DID = "did:plc:another2345"
NOW = 2_000_000_000


def timestamp(age):
    return datetime.datetime.fromtimestamp(NOW - age, datetime.timezone.utc).isoformat()


def feed_post(name, age, *, author=DID, text="猫の写真", **record_fields):
    return {"post": {"uri": f"at://{author}/app.bsky.feed.post/{name}", "author": {"did": author},
                     "indexedAt": timestamp(age),
                     "record": {"text": text, "createdAt": timestamp(age), **record_fields}}}


class ReachOutPostsTest(unittest.TestCase):
    def setUp(self):
        self.cache = patch.object(server, "POSTS_CACHE", {})
        self.clock = patch.object(server.time, "time", return_value=NOW)
        self.cache.start()
        self.clock.start()
        self.addCleanup(self.cache.stop)
        self.addCleanup(self.clock.stop)

    def test_recent_scan_reads_reply_pages_preserves_tags_and_stops_at_old_page(self):
        facets = [{"features": [{"$type": "app.bsky.richtext.facet#tag", "tag": "結城めもり"}]}]
        reply = feed_post("reply", 3600, text="写真みて #結城めもり", tags=["結城めもり"], facets=facets,
                          reply={"parent": {"uri": "at://parent/post/1"}, "root": {"uri": "at://parent/post/1"}})
        pages = [{"feed": [feed_post("new", 60)], "cursor": "page-2"},
                 {"feed": [reply, feed_post("old", 4 * 24 * 3600)], "cursor": "too-old"}]
        with patch.object(server, "xrpc", side_effect=pages) as xrpc:
            posts = server.character_posts(DID, all_recent=True)
        self.assertEqual(xrpc.call_count, 2)
        self.assertEqual(xrpc.call_args_list[0].args, (server.APPVIEW, "app.bsky.feed.getAuthorFeed"))
        for call in xrpc.call_args_list:
            self.assertEqual(call.kwargs["actor"], DID)
            self.assertEqual(call.kwargs["limit"], 100)
            self.assertEqual(call.kwargs["filter"], "posts_with_replies")
        self.assertEqual(xrpc.call_args_list[1].kwargs["cursor"], "page-2")
        saved = next(post for post in posts if post["uri"].endswith("/reply"))
        self.assertEqual(saved["text"], "写真みて #結城めもり")
        self.assertEqual(saved["tags"], ["結城めもり"])
        self.assertEqual(saved["facets"], facets)
        self.assertEqual(saved["createdAt"], NOW - 3600)

    def test_tag_and_normal_post_caches_do_not_hide_reply_posts_from_each_other(self):
        normal = {"feed": [feed_post("normal", 60)], "cursor": "unused"}
        tagged = {"feed": [feed_post("tagged-reply", 120, text="#結城めもり")], "cursor": None}
        with patch.object(server, "xrpc", side_effect=[normal, tagged]) as xrpc:
            first = server.character_posts(DID)
            all_recent = server.character_posts(DID, all_recent=True)
            self.assertEqual(server.character_posts(DID), first)
            self.assertEqual(server.character_posts(DID, all_recent=True), all_recent)
        self.assertEqual(xrpc.call_count, 2)
        self.assertEqual(xrpc.call_args_list[0].kwargs["filter"], "posts_no_replies")
        self.assertEqual(xrpc.call_args_list[0].kwargs["limit"], 10)
        self.assertEqual([post["uri"].split("/")[-1] for post in first], ["normal"])
        self.assertEqual([post["uri"].split("/")[-1] for post in all_recent], ["tagged-reply"])

    def test_recent_repost_of_old_content_does_not_stop_scan_or_become_authors_topic(self):
        repost = feed_post("someone-else", 10 * 24 * 3600, author=OTHER_DID, text="#結城めもり")
        repost["reason"] = {"$type": "app.bsky.feed.defs#reasonRepost", "indexedAt": timestamp(60)}
        pages = [{"feed": [repost], "cursor": "next"},
                 {"feed": [feed_post("own-tagged", 3600, text="#結城めもり")], "cursor": None}]
        with patch.object(server, "xrpc", side_effect=pages) as xrpc:
            posts = server.character_posts(DID, all_recent=True)
        self.assertEqual(xrpc.call_count, 2)
        self.assertEqual([post["uri"].split("/")[-1] for post in posts], ["own-tagged"])

    def test_tag_feed_refreshes_after_one_check_while_normal_cache_stays_valid(self):
        pages = [{"feed": [feed_post("normal", 60)]}, {"feed": []},
                 {"feed": [feed_post("new-tagged", 0, text="#結城めもり")]}]
        with patch.object(server, "xrpc", side_effect=pages) as xrpc:
            normal = server.character_posts(DID)
            self.assertEqual(server.character_posts(DID, all_recent=True), [])
            server.time.time.return_value = NOW + server.automation.POST_CHECK + 1
            self.assertEqual(server.character_posts(DID), normal)
            posts = server.character_posts(DID, all_recent=True)
        self.assertEqual(xrpc.call_count, 3)
        self.assertEqual([post["uri"].split("/")[-1] for post in posts], ["new-tagged"])
