#!/usr/bin/env python3
"""Compare this docs tree with upstream without treating moved pages as rewrites.

Run from any directory:
    py scripts/generate-upstream-diff.py --upstream-ref upstream/main --working-tree

Only Git-tracked files are read in working-tree mode. Generated reports, this
script, and the report page are excluded so regenerating cannot include itself.
The JSON inventory records every path move. The patch removes the local content
root prefixes from paths and text to expose substantive edits separately.
"""

import argparse
import difflib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED = {
    'scripts/generate-upstream-diff.py',
    'docs/en/resources/tino-changes.mdx',
}
OUTPUT_PREFIX = 'public/tino-changes/'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def tree(ref):
    entries = {}
    for item in git('ls-tree', '-rz', ref).split(b'\0'):
        if not item:
            continue
        info, path = item.split(b'\t', 1)
        mode, kind, sha = info.decode().split()
        if kind == 'blob':
            entries[path.decode('utf-8')] = sha
    return entries


def blobs(shas):
    ordered = sorted(set(shas))
    output = subprocess.check_output(
        ['git', 'cat-file', '--batch'], cwd=ROOT,
        input=('\n'.join(ordered) + '\n').encode(),
    )
    result, offset = {}, 0
    for expected in ordered:
        end = output.index(b'\n', offset)
        sha, kind, size = output[offset:end].decode().split()
        assert sha == expected and kind == 'blob'
        offset = end + 1
        result[sha] = output[offset:offset + int(size)]
        offset += int(size) + 1
    return result


def upstream_path(path):
    if path.startswith('docs/en/'):
        return path.removeprefix('docs/en/')
    if path.startswith('docs/i18n/'):
        return path.removeprefix('docs/i18n/')
    return path


def normalized(data):
    if b'\0' in data:
        return None
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return None
    text = text.replace('\r\n', '\n').replace('docs/en/', '').replace('docs/i18n/', '')
    return text if not text or text.endswith('\n') else text + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream-ref', default='upstream/main')
    parser.add_argument('--local-ref', default='HEAD')
    parser.add_argument('--working-tree', action='store_true')
    args = parser.parse_args()
    upstream_sha = git('rev-parse', args.upstream_ref).decode().strip()
    local_sha = git('rev-parse', args.local_ref).decode().strip()
    before = tree(upstream_sha)
    after = tree(local_sha)
    content = blobs([*before.values(), *after.values()])

    if args.working_tree:
        # ls-files deliberately excludes untracked personal files and research.
        local_data = {
            path: (ROOT / path).read_bytes()
            for path in git('ls-files', '-z').decode().split('\0')
            if path and (ROOT / path).is_file()
        }
    else:
        local_data = {path: content[sha] for path, sha in after.items()}

    local_data = {
        path: data for path, data in local_data.items()
        if path not in EXCLUDED and not path.startswith(OUTPUT_PREFIX)
    }
    mapped = {upstream_path(path): (path, data) for path, data in local_data.items()}
    assert len(mapped) == len(local_data), 'Duplicate paths after normalization'
    inventory, patch = [], []
    counts = {'unchanged': 0, 'moved_or_path_only': 0, 'modified': 0, 'added': 0, 'removed': 0}
    for path in sorted(set(before) | set(mapped)):
        old = content[before[path]] if path in before else b''
        local_path, new = mapped.get(path, (None, b''))
        old_text, new_text = normalized(old), normalized(new)
        if path not in before:
            status = 'added'
        elif local_path is None:
            status = 'removed'
        elif old_text == new_text and (old_text is not None or old == new):
            status = 'moved_or_path_only' if path != local_path or old != new else 'unchanged'
        else:
            status = 'modified'
        counts[status] += 1
        if status == 'unchanged':
            continue
        inventory.append({'upstream_path': path if path in before else None,
                          'local_path': local_path, 'status': status})
        if status == 'moved_or_path_only':
            continue
        if old_text is None or new_text is None:
            patch.append(f'Binary file differs: {path}\n')
        else:
            patch.extend(difflib.unified_diff(
                old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
                fromfile='upstream/' + path if path in before else '/dev/null',
                tofile='local/' + path if local_path else '/dev/null',
            ))

    report = {
        'upstream_repository': 'raydium-io/raydium-docs-v1',
        'upstream_commit': upstream_sha,
        'local_base_commit': local_sha,
        'includes_tracked_working_tree': args.working_tree,
        'normalization': 'docs/en/ becomes the upstream root; docs/i18n/<locale>/ becomes <locale>/. These prefixes are also removed from text. LF line endings and a final newline are used.',
        'excluded': [*sorted(EXCLUDED), OUTPUT_PREFIX + '*', 'all untracked files'],
        'counts': counts,
        'files': inventory,
    }
    destination = ROOT / OUTPUT_PREFIX
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'upstream-content.patch').write_text(''.join(patch), encoding='utf-8', newline='\n')
    (destination / 'upstream-diff.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'upstream_commit': upstream_sha, 'local_base_commit': local_sha, 'counts': counts}))


if __name__ == '__main__':
    main()
