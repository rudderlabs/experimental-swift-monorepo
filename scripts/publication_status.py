"""Report customer publication separately from internal Release Please intent."""
import json
import os
from pathlib import Path
import re
import tempfile

from common import load, run


def summarize(plan, jobs):
    packages = {}
    for item in plan:
        key = item['package']
        job = jobs.get(key, {})
        outputs = job.get('outputs', {})
        expected = {'package': key, 'version': item.get('version'), 'sourceCommit': item.get('sha')}
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
                         'pullRequest': outputs.get('pullRequest') if waiting else None,
                         'publicationCommit': outputs.get('publicationCommit') if verified else None}
    status = ('no_release' if not packages else
              'incomplete' if any(p['status'] == 'incomplete' for p in packages.values()) else
              'published' if all(p['status'] == 'published' for p in packages.values()) else 'awaiting_publication')
    return {'status': status, 'packages': packages,
            'note': 'Incomplete jobs may already have served a tag; inspect refs before retrying. '
                    'Source component releases are internal intent, not customer publication evidence.'}


def collect(plan, download):
    """Matrix legs share one output slot, so each publish job leaves its result in its own artifact."""
    jobs = {}
    for item in plan:
        folder = download(f"publication-{item['package']}-{item['version']}")
        if folder is None:
            continue
        job, result = folder / 'publication-job.json', folder / 'publication-result.json'
        jobs[item['package']] = {'result': load(job)['result'] if job.exists() else 'missing',
                                 'outputs': load(result) if result.exists() else {}}
    return jobs


if __name__ == '__main__':
    plan = json.loads(os.environ['RELEASE_PLAN'])
    with tempfile.TemporaryDirectory(prefix='publication-status-') as temp:
        def download(name):
            try:
                run(['gh', 'run', 'download', os.environ['GITHUB_RUN_ID'], '--repo', os.environ['GITHUB_REPOSITORY'],
                     '--name', name, '--dir', Path(temp) / name])
            except RuntimeError:
                return None
            return Path(temp) / name
        result = summarize(plan, collect(plan, download))
    text = json.dumps(result, indent=2) + '\n'
    Path(os.environ['PUBLICATION_STATUS_FILE']).write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
            summary.write('Customer publication: **' + result['status'] + '**\n\n```json\n' + text + '```\n')
    print(text, end='')
    raise SystemExit(1 if result['status'] == 'incomplete' else 0)
