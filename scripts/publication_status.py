"""Report customer publication separately from internal Release Please intent."""
import json
import os
from pathlib import Path
import re

from common import NAMES


def summarize(intent, jobs):
    packages = {}
    for key in NAMES:
        if str(intent.get(key + '_created', '')).lower() != 'true':
            continue
        job = jobs.get(key, {})
        outputs = job.get('outputs', {})
        expected = {'package': key, 'version': intent.get(key + '_version'),
                    'sourceCommit': intent.get(key + '_sha')}
        verified = (job.get('result') == 'success'
                    and outputs.get('status') == 'published'
                    and all(outputs.get(field) == value and value for field, value in expected.items())
                    and outputs.get('tag') == expected['version']
                    and bool(re.fullmatch('[0-9a-f]{40}', outputs.get('publicationCommit', ''))))
        waiting = (job.get('result') == 'success'
                   and outputs.get('status') in ('awaiting_review', 'awaiting_dependency')
                   and all(outputs.get(field) == value and value for field, value in expected.items()))
        state = 'published' if verified else outputs['status'] if waiting else 'incomplete'
        packages[key] = {**expected, 'status': state,
                         'jobResult': job.get('result', 'missing'),
                         'publicationCommit': outputs.get('publicationCommit') if verified else None}
    status = ('no_release' if not packages else
              'incomplete' if any(p['status'] == 'incomplete' for p in packages.values()) else
              'published' if all(p['status'] == 'published' for p in packages.values()) else 'awaiting_publication')
    return {'status': status, 'packages': packages,
            'note': 'Incomplete jobs may already have served a tag; inspect refs before retrying. '
                    'Source component releases are internal intent, not customer publication evidence.'}


if __name__ == '__main__':
    result = summarize(json.loads(os.environ['RELEASE_INTENT']), json.loads(os.environ['PUBLICATION_JOBS']))
    text = json.dumps(result, indent=2) + '\n'
    Path(os.environ['PUBLICATION_STATUS_FILE']).write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
            summary.write('Customer publication: **' + result['status'] + '**\n\n```json\n' + text + '```\n')
    print(text, end='')
    raise SystemExit(1 if result['status'] == 'incomplete' else 0)
