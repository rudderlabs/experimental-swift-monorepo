"""Recovery comes from source releases, not transient Release Please outputs."""
import os
from pathlib import Path
import sys
import unittest

os.environ["GIT_CONFIG_GLOBAL"] = os.devnull  # ignore personal git settings such as tag.gpgsign
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from publication_queue import queue
import json


class PublicationQueueTests(unittest.TestCase):
    def run_queue(self, published=False, wrong_source=False, release_missing=False):
        sha, pub = 'a' * 40, 'b' * 40
        intents = [{'tag_name': 'integration-sprig-0.1.1', 'draft': False, 'prerelease': False},
                   {'tag_name': 'unrelated-1.0.0', 'draft': False, 'prerelease': False},
                   {'tag_name': 'sdk-0.2.0', 'draft': True, 'prerelease': False}]
        body = f'Temporary unsupported experiment.\n\nSource: {sha}\nPublication: {pub}\n'
        def command(args, **kwargs):
            if args[:2] == ['git', 'clone']:
                return ''
            if 'experimental-swift-monorepo/releases?' in args[-1]:
                return json.dumps([intents])
            return json.dumps([[{'tag_name': '0.1.1', 'draft': False, 'body': body}]]
                              if published and not release_missing and 'sprig/releases?' in args[-1] else [[]])
        def git_command(repo, *args):
            if args[0] == 'rev-parse':
                return sha if repo == Path('/source') else pub
            if args[0] == 'for-each-ref':
                return 'refs/tags/0.1.1' if published else ''
            return ''
        with patch('publication_queue.run', side_effect=command), \
             patch('publication_queue.git', side_effect=git_command), \
             patch('publication_queue.verify_tree', return_value={
                 'sourceCommit': 'c' * 40 if wrong_source else sha, 'package': 'sprig', 'version': '0.1.1'}):
            return queue(Path('/source'))

    def test_pending_release_is_recovered_without_action_outputs(self):
        self.assertEqual(self.run_queue(), [{'package': 'sprig', 'version': '0.1.1', 'source_sha': 'a' * 40}])

    def test_complete_publication_is_not_repeated(self):
        self.assertEqual(self.run_queue(published=True), [])

    def test_tag_without_release_stays_in_recovery_queue(self):
        self.assertEqual(len(self.run_queue(published=True, release_missing=True)), 1)

    def test_conflicting_public_tag_stops(self):
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            self.run_queue(published=True, wrong_source=True)
