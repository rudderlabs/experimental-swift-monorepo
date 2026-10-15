"""Public Release and publish-PR notes follow the standalone RudderStack Swift repositories."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from release_notes import display_name, notes, previous_tag, references, release_body, sections

MONO = 'https://github.com/rudderlabs/experimental-swift-monorepo'
CHANGELOG = f'''# Changelog

## [1.4.1]({MONO}/compare/swift-sdk-1.4.0...swift-sdk-1.4.1) (2026-10-12)


### Code Refactoring

* **swift-sdk:** read RSVersion from Version.swift ([#25]({MONO}/issues/25)) ([a9f1b45]({MONO}/commit/a9f1b4571ac106bf50b1086c8c2f4a3984f26422))


### Bug Fixes

* fix one ([#30]({MONO}/issues/30)) ([1234567]({MONO}/commit/1234567890abcdef1234567890abcdef12345678)), closes [#31]({MONO}/issues/31)
* fix two ([#25]({MONO}/issues/25))

# [1.4.0](https://github.com/rudderlabs/rudder-sdk-swift/compare/1.3.1...1.4.0) (2026-09-22)


### Features

* **consent:** older entry ([#254](https://github.com/rudderlabs/rudder-sdk-swift/issues/254))

## [1.3.1] - 2026-08-10

### Bug Fixes

- hand-written entry (#249)
'''
SDK = {'target': 'RudderStackAnalytics', 'title': 'RudderStack Swift SDK', 'repository': 'experimental-rudder-sdk-swift'}
PROVENANCE = {'sourceCommit': 'a' * 40, 'sourceRepository': 'rudderlabs/experimental-swift-monorepo'}


class ReleaseNotesTests(unittest.TestCase):
    def test_changelog_section_becomes_the_public_format(self):
        self.assertEqual(notes('swift-sdk', SDK, '1.4.1', CHANGELOG),
                         '# RudderStack Swift SDK 1.4.1\n\n'
                         '## Bug Fixes\n'
                         f'- fix one ([#30]({MONO}/pull/30))\n'
                         f'- fix two ([#25]({MONO}/pull/25))\n'
                         '## Code Refactoring\n'
                         f'- read RSVersion from Version.swift ([#25]({MONO}/pull/25))\n')

    def test_section_boundaries_and_heading_levels(self):
        self.assertEqual(sections(CHANGELOG, '1.4.0'), {'Features': [
            '- older entry ([#254](https://github.com/rudderlabs/rudder-sdk-swift/pull/254))']})
        self.assertEqual(sections(CHANGELOG, '1.3.1'), {'Bug Fixes': ['- hand-written entry (#249)']})
        self.assertEqual(sections(CHANGELOG, '9.9.9'), {})
        self.assertEqual(notes('swift-sdk', SDK, '9.9.9', CHANGELOG), '# RudderStack Swift SDK 9.9.9\n')
        self.assertEqual(sections('## 0.1.0\n\nLocal lifecycle rehearsal.\n', '0.1.0'),
                         {'': ['Local lifecycle rehearsal.']})

    def test_display_name_defaults_to_the_target(self):
        self.assertEqual(display_name('sprig', {'target': 'RudderIntegrationSprig'}), 'RudderIntegrationSprig')
        self.assertEqual(display_name('sprig', None), 'sprig')

    def test_release_body_with_whats_changed_compare_and_provenance(self):
        prs = {25: ('refactor(swift-sdk): read RSVersion from Version.swift', 'SKannaniOS'), 30: ('fix: one', 'someone')}
        def gh(args, **kwargs):
            number = int(args[-1].rsplit('/', 1)[1])
            return json.dumps({'title': prs[number][0], 'user': {'login': prs[number][1]},
                               'html_url': f'{MONO}/pull/{number}'})
        with patch('release_notes.run', side_effect=gh) as command:
            body = release_body('swift-sdk', SDK, '1.4.1', CHANGELOG, PROVENANCE, previous='1.4.0')
        self.assertEqual([c.args[0][-1] for c in command.call_args_list],
                         ['repos/rudderlabs/experimental-swift-monorepo/pulls/30',
                          'repos/rudderlabs/experimental-swift-monorepo/pulls/25'])
        self.assertTrue(body.startswith('# RudderStack Swift SDK 1.4.1\n\n## Bug Fixes\n'))
        self.assertIn("\n\n## What's Changed\n"
                      f'* fix: one by @someone in {MONO}/pull/30\n'
                      f'* refactor(swift-sdk): read RSVersion from Version.swift by @SKannaniOS in {MONO}/pull/25\n\n'
                      '**Full Changelog**: https://github.com/rudderlabs/experimental-rudder-sdk-swift/compare/'
                      '1.4.0...1.4.1\n\n', body)
        self.assertTrue(body.endswith(f'Source: monorepo commit {MONO}/commit/{"a" * 40}\n'))

    def test_whats_changed_is_best_effort(self):
        with patch('release_notes.run', side_effect=RuntimeError('403')):
            body = release_body('swift-sdk', SDK, '1.4.1', CHANGELOG, PROVENANCE)
        self.assertNotIn("What's Changed", body)
        self.assertNotIn('Full Changelog', body)
        self.assertIn('## Code Refactoring', body)
        with patch('release_notes.run', side_effect=AssertionError('no network offline')):
            self.assertEqual(release_body('swift-sdk', SDK, '1.4.1', CHANGELOG, PROVENANCE, online=False), body)

    def test_references_and_previous_tag(self):
        self.assertEqual(references(notes('swift-sdk', SDK, '1.4.1', CHANGELOG)),
                         [('rudderlabs/experimental-swift-monorepo', 30), ('rudderlabs/experimental-swift-monorepo', 25)])
        self.assertEqual(previous_tag(['1.2.0', '1.10.0', '1.9.3', '2.0.0', 'swift-sdk-1.9.9', 'v1.9.9'], '1.10.1'),
                         '1.10.0')
        self.assertEqual(previous_tag(['1.10.0', '1.9.3'], '1.10.0'), '1.9.3')
        self.assertIsNone(previous_tag(['1.0.0'], '1.0.0'))


if __name__ == '__main__':
    unittest.main()
