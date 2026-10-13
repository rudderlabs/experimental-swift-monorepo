"""Public release notes in the format of the standalone RudderStack Swift repositories.

The package's CHANGELOG.md section for a version (Release Please writes it) becomes `## Features`,
`## Bug Fixes`, ... with `- entry ([#N](url))` lines. PR links keep full URLs: they point at the
monorepo, and a bare `#N` would resolve against the public repository.
"""
import json
import re

from common import OWNER, SOURCE_NAME, run, text

# Sections in the order the existing public Releases use; unknown sections follow in changelog order.
ORDER = ('⚠ BREAKING CHANGES', 'Features', 'Bug Fixes', 'Performance Improvements', 'Reverts', 'Code Refactoring',
         'Documentation', 'Styles', 'Tests', 'Build System', 'Continuous Integration', 'Chores',
         'Miscellaneous Chores', 'Dependencies')
HEADING = re.compile(r'#{1,2} ')
VERSION = re.compile(r'#{1,2} \[?v?(\d+\.\d+\.\d+)\b')
SCOPE = re.compile(r'^\*\*[^*\n]+:\*\* ')
COMMIT_LINK = re.compile(r'\s*\(\[[0-9a-f]*\]\(https://github\.com/[^)\s]+/commit/[0-9a-f]+\)\)')
CLOSES = re.compile(r',? closes \[#\d+\]\([^)]*\)(?:, \[#\d+\]\([^)]*\))*\s*$')
REFERENCE = re.compile(r'\[#(\d+)\]\(https://github\.com/([\w.-]+/[\w.-]+)/(?:issues|pull)/\1\)')
SEMVER = re.compile(r'(\d+)\.(\d+)\.(\d+)\Z')


def display_name(key, package):
    """`title` from release/packages.json, else the target name."""
    return (package or {}).get('title') or (package or {}).get('target') or key


def entry(line):
    value = SCOPE.sub('', line[2:].strip())
    value = CLOSES.sub('', COMMIT_LINK.sub('', value)).rstrip()
    return '- ' + REFERENCE.sub(lambda m: f'[#{m[1]}](https://github.com/{m[2]}/pull/{m[1]})', value)


def sections(changelog, version):
    """The version's changelog section as {name: [lines]}; '' holds text before the first subsection."""
    found, current, result = False, '', {}
    for line in changelog.splitlines():
        if HEADING.match(line):
            match = VERSION.match(line)
            if found:
                break
            found = bool(match and match[1] == version)
            continue
        if not found:
            continue
        if line.startswith('### '):
            current = line[4:].strip()
            result.setdefault(current, [])
        elif line.startswith(('* ', '- ')):
            result.setdefault(current, []).append(entry(line))
        elif line.strip() and line[:1].isspace() and result.get(current):
            result[current][-1] += '\n' + line.rstrip()
        elif line.strip():
            result.setdefault(current, []).append(line.rstrip())
    return {name: lines for name, lines in result.items() if lines}


def notes(key, package, version, changelog):
    """`# <title> <version>` and the changelog sections: the shared block of the Release and the publish PR."""
    found = sections(changelog, version)
    names = [n for n in ORDER if n in found] + [n for n in found if n not in ORDER and n]
    lines = [text('notesHeading', title=display_name(key, package), version=version), '']
    lines += found.get('', []) + ([''] if found.get('') else [])
    for name in names:
        lines += ['## ' + name, *found[name]]
    return '\n'.join(lines).rstrip('\n') + '\n'


def references(block):
    seen = []
    for match in REFERENCE.finditer(block):
        if (match[2], int(match[1])) not in seen:
            seen.append((match[2], int(match[1])))
    return seen


def whats_changed(block):
    """The What's Changed list of the PRs the entries link. Best effort: any API error omits the section."""
    try:
        lines = []
        for repository, number in references(block):
            pr = json.loads(run(['gh', 'api', f'repos/{repository}/pulls/{number}']))
            lines.append(text('pullRequestLine', title=pr['title'], author=pr['user']['login'], url=pr['html_url']))
    except (RuntimeError, ValueError, KeyError, TypeError, OSError):
        return ''
    return '\n'.join([text('whatsChanged'), *lines]) + '\n' if lines else ''


def previous_tag(tags, version):
    """The highest plain SemVer tag below `version`, or None."""
    key = lambda tag: tuple(map(int, SEMVER.match(tag).groups()))
    older = [t for t in tags if SEMVER.match(t) and key(t) < key(version)]
    return max(older, key=key) if older else None


def release_body(key, package, version, changelog, provenance, previous=None, online=True):
    block = notes(key, package, version, changelog)
    parts = [block, whats_changed(block) if online else '']
    if previous:
        parts.append(text('fullChangelog', repository=f'{OWNER}/{package["repository"]}',
                          previous=previous, version=version))
    parts.append(text('releaseFooter', repository=provenance.get('sourceRepository', f'{OWNER}/{SOURCE_NAME}'),
                      source=provenance['sourceCommit']))
    return '\n\n'.join(p.rstrip('\n') for p in parts if p) + '\n'
