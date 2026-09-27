"""v7 evidence gates. Records observable work; does not prove semantic truth."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import unicodedata
from datetime import datetime, timezone

_HISTORY_CACHE = {}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local(root, rel):
    p = root / rel
    if Path(rel).is_absolute() or not p.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'path outside root: {rel}')
    return p


def load(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, encoding='utf-8', delete=False) as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(f.name, path)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def history(wiki):
    path = local(wiki, '_meta/history.jsonl')
    stat = path.stat() if path.exists() else None
    signature = (stat.st_size, stat.st_mtime_ns) if stat else None
    cached = _HISTORY_CACHE.get(path)
    if cached and cached[0] == signature:
        return cached[1]
    events, previous = [], None
    for line in path.read_text().splitlines() if path.exists() else []:
        e = json.loads(line)
        unsigned = {k: v for k, v in e.items() if k != 'hash'}
        if e.get('previous') != previous or e.get('hash') != digest(unsigned):
            raise ValueError('history chain damaged; preserve evidence and repair provenance, do not reset')
        events.append(e); previous = e['hash']
    _HISTORY_CACHE[path] = (signature, events)
    return events


def append_event(wiki, event):
    events = history(wiki)
    event = dict(event, observed_at=datetime.now(timezone.utc).isoformat(),
                 previous=events[-1]['hash'] if events else None)
    event['hash'] = digest(event)
    path = local(wiki, '_meta/history.jsonl'); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(event, ensure_ascii=False) + '\n')
        f.flush(); os.fsync(f.fileno())
    return event['hash']


def begin_attempt(args):
    wiki = args.wiki.resolve()
    review = load(args.review_file) if args.review_file else None
    previous = {n: load(local(wiki, '_meta/' + n)) for n in ('analysis.json', 'workflow.json')}
    return append_event(wiki, {'event': 'attempt', 'command': args.command, 'page': args.page,
                              'reason': args.reason, 'reuse_existing': args.reuse_existing,
                              'review': review, 'previous_stages': previous if args.command in {'analyze', 'plan'} else None})


def end_attempt(args, attempt, code, error=None):
    wiki = args.wiki.resolve()
    # Retain full previous versions through the event chain, not just the latest seal.
    names = {'analyze': ['analysis.json'], 'plan': ['workflow.json', 'plan.json'],
             'checkpoint': ['state.json'], 'scope-review': ['scope-review.json']}
    artifacts = {name: load(local(wiki, '_meta/' + name)) for name in names.get(args.command, [])}
    if args.command == 'checkpoint':
        artifacts['state.json'] = (artifacts.get('state.json') or {}).get(args.page)
    append_event(wiki, {'event': 'result', 'attempt': attempt, 'command': args.command,
                       'page': args.page, 'exit_code': code, 'error': error, 'artifacts': artifacts})


def require_recorded(wiki, command, name, value, page=None):
    results = [e for e in history(wiki) if e.get('event') == 'result' and
               e.get('command') == command and e.get('page') == page and e.get('exit_code') == 0]
    if not results or results[-1]['artifacts'].get(name) != value:
        raise ValueError(f'{command} seal has no matching successful history; old chronology is unverified')


def read_source(repo, wiki, source, start=None, end=None):
    p = local(repo, source)
    if p.is_symlink() or p.resolve().is_relative_to(wiki.resolve()):
        raise ValueError('read the actual repository source, not symlinks or generated wiki')
    raw = p.read_bytes()
    body = raw.decode('utf-8-sig')
    if '\0' in body:
        raise ValueError('binary input requires structured inspection, not text reading')
    lines = body.splitlines(); total = len(lines)
    start = 1 if start is None else start
    end = total if end is None else end
    if not ((total == 0 and start == 1 and end == 0) or 1 <= start <= end <= total):
        raise ValueError(f'invalid read range: {start}-{end} of {total}; never clamp ranges')
    source_hash = hashlib.sha256(raw).hexdigest()
    receipt = {'path': source, 'sha256': source_hash, 'start': start, 'end': end, 'lines': total}
    print(json.dumps({'read_receipt': receipt}, ensure_ascii=False))
    for n in range(start, end + 1):
        print(f'{n}: {lines[n - 1]}')
    # A receipt proves the command exposed bytes, not that the model understood them.
    receipt['event'] = 'read'
    append_event(wiki, receipt)
    return 0


def validate_reading(repo, wiki, review, inventory):
    if review.get('schema_version') != 7:
        raise ValueError('v7 analysis-review schema required; legacy read flags need evidence')
    events = history(wiki)
    for row in review['files']:
        rel = row['path']
        if row['status'] == 'read':
            if row.get('method') == 'structured':
                report = row.get('inspection', {})
                if report.get('source_sha256') != inventory[rel]:
                    raise ValueError(f'structured inspection source hash missing/stale: {rel}')
                path = local(wiki, report.get('report', ''))
                if (not path.is_file() or not path.relative_to(wiki).as_posix().startswith('_meta/') or
                        sha(path) != report.get('report_sha256') or not text(report.get('method'))):
                    raise ValueError(f'structured inspection needs a bound actual report and method: {rel}')
                raw = local(repo, rel).read_bytes()
                try:
                    decoded = raw.decode('utf-8-sig')
                except UnicodeError:
                    decoded = '\0'
                if '\0' not in decoded:
                    raise ValueError(f'text source needs full_text; AST or symbol extraction is not full reading: {rel}')
                continue
            if row.get('method') != 'full_text':
                raise ValueError(f'sampling/AST/headers are partial reading: {rel}')
            ranges = sorted((e['start'], e['end']) for e in events if e.get('event') == 'read' and
                            e.get('path') == rel and e.get('sha256') == inventory[rel])
            lines = len(local(repo, rel).read_text(encoding='utf-8-sig').splitlines())
            cursor = 1
            for a, b in ranges:
                if a > cursor:
                    break
                cursor = max(cursor, b + 1)
            if not ranges or cursor <= lines:
                raise ValueError(f'missing current full-text read receipts: {rel}, next line {cursor}')
        elif row['status'] == 'nonsemantic':
            # A deliberate classification; source/config/database files cannot be hidden here.
            if row.get('category') not in {'cache', 'build_output', 'duplicate', 'asset'}:
                raise ValueError(f'nonsemantic file needs an explicit category: {rel}')
            duplicate = row.get('duplicate_of')
            if (row['category'] == 'duplicate' and duplicate != rel and duplicate in inventory and
                    inventory[duplicate] == inventory[rel] and
                    any(f['path'] == duplicate and f['status'] == 'read' for f in review['files'])):
                continue  # An identical, actually read source need not be read twice.
            if Path(rel).suffix.lower() in {'.c', '.h', '.cpp', '.hpp', '.py', '.js', '.ts', '.rs',
                                           '.sh', '.ps1', '.sql', '.sqlite', '.sqlite3', '.db',
                                           '.json', '.yaml', '.yml', '.toml', '.xml', '.dbc'}:
                raise ValueError(f'source/config input cannot be silently classified nonsemantic: {rel}')


def anchors(repo, records, allowed):
    if not isinstance(records, list) or not records:
        raise ValueError('source_anchors must contain actual source ranges and exact quotations')
    for a in records:
        rel = a['path']
        if rel not in allowed:
            raise ValueError(f'uncaptured source anchor: {rel}')
        lines = local(repo, rel).read_text(encoding='utf-8-sig').splitlines()
        start, end = a['start'], a['end']
        if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines):
            raise ValueError(f'invalid evidence range: {rel}; do not clamp to header/EOF')
        if not text(a.get('quote')) or a['quote'] not in '\n'.join(lines[start-1:end]):
            raise ValueError(f'source quote does not occur in the stated range: {rel}:{start}-{end}')


def capability_analysis(repo, review, inventory):
    seen = set()
    for m in review['modules']:
        caps = m.get('capabilities')
        if not isinstance(caps, list) or not caps:
            raise ValueError(f"enumerate independent capabilities before grouping pages: {m['id']}")
        for c in caps:
            if not text(c.get('id')) or c['id'] in seen or not text(c.get('name')) or not text(c.get('description')):
                raise ValueError('capabilities require globally unique IDs and specific findings')
            seen.add(c['id'])
            anchors(repo, c.get('source_anchors'), inventory)
            if not all(any(Path(a['path']).is_relative_to(Path(p)) for p in m['paths']) for a in c['source_anchors']):
                raise ValueError(f"capability evidence outside its module: {c['id']}")


def module_directory_issues(plan, wiki=None, check_files=False):
    """Enforce physical module folders; logical parents alone do not organize files."""
    issues, directories, owners = [], {}, {}
    shared_roots = {'_overview', '_flows'}
    root_pages = {'README.md', 'REPORT.md'}

    def parts(rel):
        if (not text(rel) or '\\' in rel or ':' in rel or
                any(p in {'', '.', '..'} for p in rel.split('/')) or PurePosixPath(rel).is_absolute()):
            raise ValueError(f'expected normalized wiki-relative path: {rel}')
        return tuple(unicodedata.normalize('NFC', p).casefold() for p in PurePosixPath(rel).parts)

    def under(child, parent):
        return len(child) > len(parent) and child[:len(parent)] == parent

    for module in plan.get('modules', []):
        if not isinstance(module, dict):
            issues.append('invalid module folder declaration'); continue
        key, directory = module.get('id'), module.get('directory')
        try:
            d = parts(directory)
            if len(d) < 2 or d[0] != 'content' or d[1] in shared_roots or '_meta' in d:
                raise ValueError(f'{key}: module directory must be its own folder under content/: {directory}')
            if d in directories:
                raise ValueError(f'{key}: module directory already owned by {directories[d]}: {directory}')
            directories[d] = key
            for page in module.get('pages', []):
                if not under(parts(page), d):
                    issues.append(f'{key}: module page outside its directory {directory}: {page}')
                if page in owners:
                    issues.append(f'module page cannot have multiple owners: {page}')
                owners[page] = key
            if wiki:
                target = local(wiki, directory)
                if target.exists() and not target.is_dir():
                    issues.append(f'module directory is a file: {directory}')
                if any((wiki.joinpath(*PurePosixPath(directory).parts[:n])).is_symlink()
                       for n in range(1, len(d) + 1)):
                    issues.append(f'module directory cannot alias another location: {directory}')
        except (ValueError, TypeError) as exc:
            issues.append(str(exc))
    page_locations = set()
    for page in plan.get('pages', []):
        rel = page['path']
        try:
            p = parts(rel)
            if p in page_locations:
                issues.append(f'page paths collide after case/Unicode normalization: {rel}')
            page_locations.add(p)
            matches = [d for d in directories if under(p, d)]
            expected = directories[max(matches, key=len)] if matches else None
            if expected is not None:
                if owners.get(rel) != expected:
                    issues.append(f'page must belong to its nearest module directory ({expected}): {rel}')
            elif rel not in root_pages and not (len(p) >= 3 and p[0] == 'content' and p[1] in shared_roots):
                issues.append(f'page needs a module folder or explicit overview/flow location: {rel}')
        except (ValueError, TypeError) as exc:
            issues.append(str(exc))
    if wiki and check_files:
        declared = {p['path'] for p in plan['pages']}
        for path in wiki.rglob('*'):
            rel = path.relative_to(wiki)
            if '_meta' in rel.parts or path.suffix.lower() != '.md' or not path.is_file():
                continue
            if rel.as_posix() not in declared and rel.as_posix() not in root_pages:
                issues.append(f'unplanned Wiki page; classify into its module and update plan: {rel}')
    return issues


def capability_plan(wiki, plan, analysis, require_body=False):
    planned = {p['path']: p for p in plan['pages']}
    locations = set()
    for module in analysis['review']['modules']:
        m = next((m for m in plan['modules'] if m['id'] == module['id']), {})
        entries = m.get('capabilities', [])
        expected = {c['id'] for c in module['capabilities']}
        if len(entries) != len(expected) or {c['id'] for c in entries} != expected:
            raise ValueError(f"every independent capability needs a page task: {module['id']}")
        for c in entries:
            page = planned.get(c.get('page'), {})
            if (c.get('page') not in m['pages'] or not text(c.get('section')) or
                    c['section'] not in page.get('sections', []) or
                    c.get('question') not in page.get('questions', [])):
                raise ValueError(f"capability needs its own explanation heading and question: {c['id']}")
            loc = (c['page'], c['section'])
            if loc in locations:
                raise ValueError('independent capabilities need distinct explanation sections; split coarse groupings')
            locations.add(loc)
            for kind in ('call', 'sequence'):
                if not text(c.get('diagram_coverage', {}).get(kind)):
                    raise ValueError(f"explain how the module {kind} diagram covers {c['id']}")
            if require_body and not section_text(local(wiki, c['page']), c['section']).strip():
                raise ValueError(f"capability explanation absent: {c['id']}")


def section_text(path, heading):
    lines, active, fence, out = path.read_text().splitlines(), False, None, []
    for line in lines:
        mark = re.match(r'^\s*(`{3,}|~{3,})', line)
        if mark:
            token = mark[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is not None:
            continue
        if re.match(r'^#{1,6} ', line):
            if active:
                break
            active = line.strip() == heading
        elif active:
            out.append(line)
    return '\n'.join(out)


def resolve_findings(repo, wiki, command, page, review, inputs):
    prior = set()
    for e in history(wiki):
        if e.get('event') == 'attempt' and e.get('command') == command and e.get('page') == page:
            prior.update(str(f) for f in (e.get('review') or {}).get('open_findings', []))
    resolved = review.get('resolutions', [])
    if prior - {r.get('finding') for r in resolved}:
        raise ValueError('previous findings require explicit resolutions; do not clear the list to pass')
    for r in resolved:
        if not text(r.get('change')):
            raise ValueError('finding resolution needs the concrete correction/recheck')
        anchors(repo, r.get('source_anchors'), inputs)


def scope_capabilities(repo, wiki, plan, review, inventory):
    expected = {c['id'] for m in plan['modules'] for c in m['capabilities']}
    checks = review.get('capability_checks', [])
    if len(checks) != len(expected) or {c.get('id') for c in checks} != expected:
        raise ValueError('scope review must reconcile every independent capability against repository entrypoints')
    for c in checks:
        if c.get('status') != 'pass' or not text(c.get('assessment')):
            raise ValueError('capability still lacks an actual explanation/coverage assessment')
        anchors(repo, c.get('source_anchors'), inventory)
    resolve_findings(repo, wiki, 'scope-review', None, review, inventory)


def review_evidence(repo, wiki, plan, page, review, snapshot):
    conclusions = []
    for a in review['answers']:
        conclusion = re.sub(r'\s+', '', a['conclusion'])
        if conclusion in conclusions:
            raise ValueError('different reader questions cannot reuse the same review conclusion')
        conclusions.append(conclusion)
        excerpt = a.get('body_quote')
        if not text(excerpt) or excerpt not in section_text(local(wiki, page['path']), a['section']):
            raise ValueError('answer body_quote must occur under its exact heading')
        anchors(repo, a.get('source_anchors'), snapshot['inputs'])
        if not set(a['sources']).issuperset(x['path'] for x in a['source_anchors']):
            raise ValueError('answer source files and anchors disagree')
    expected = {(m['id'], kind): ref for m in plan['modules'] for kind, ref in m['diagrams'].items()
                if kind in {'call', 'sequence'} and ref['page'] == page['path']}
    records = review.get('diagram_reviews', [])
    keys = [(r.get('module'), r.get('kind')) for r in records]
    if len(keys) != len(set(keys)) or set(keys) != set(expected):
        raise ValueError('review each required module call/sequence diagram separately')
    for r in records:
        ref = expected[(r['module'], r['kind'])]
        if r.get('section') != ref['section'] or r.get('status') != 'pass':
            raise ValueError('diagram review must match its actual location and result')
        fields = ('entry_and_binding', 'edge_meaning', 'non_edges') if r['kind'] == 'call' else (
            'scenario', 'ordering_and_state', 'failure_and_exit')
        if not all(text(r.get(k)) for k in fields):
            raise ValueError(f"diagram review needs concrete {', '.join(fields)}")
        anchors(repo, r.get('source_anchors'), snapshot['inputs'])
    resolve_findings(repo, wiki, 'checkpoint', page['path'], review, snapshot['inputs'])


def diagram_blocks(path):
    result, section, fence, rows, capture = [], '', None, [], False
    for line in path.read_text().splitlines():
        if fence is None:
            if re.match(r'^#{1,6} ', line):
                section = line.strip()
            m = re.match(r'^\s*(`{3,}|~{3,})(.*)$', line)
            if m:
                fence, capture, rows = m[1], m[2].strip().lower() == 'mermaid', []
        elif re.fullmatch(r'\s*' + re.escape(fence[0]) + '{' + str(len(fence)) + r',}\s*', line):
            if capture:
                result.append({'section': section, 'index': len(result), 'text': '\n'.join(rows)})
            fence = None
        else:
            rows.append(line)
    if fence is not None:
        raise ValueError(f'unclosed code fence: {path}')
    return result


def render_pages(wiki, pages):
    paths = {p['path'] for p in pages}
    paths.update(p.relative_to(wiki).as_posix() for p in wiki.rglob('*.md')
                 if '_meta' not in p.relative_to(wiki).parts)
    return [{'path': p} for p in sorted(paths)]


def rendering(wiki, pages, execute=False, renderer=None):
    receipt_path = local(wiki, '_meta/render.json')
    stored = load(receipt_path, {})
    executable = shutil.which(renderer or 'mmdc') if execute else None
    identity = None
    if executable:
        version = subprocess.run([executable, '--version'], capture_output=True, text=True, timeout=30)
        if version.returncode != 0:
            raise ValueError('Mermaid renderer version probe failed')
        identity = {'path': str(Path(executable).resolve()), 'sha256': sha(Path(executable)),
                    'version': version.stdout.strip()}
    issues, records = [], dict(stored)
    for page in pages:
        rel = page['path']; path = local(wiki, rel)
        if not path.is_file():
            issues.append(f'missing diagram page: {rel}'); continue
        blocks = diagram_blocks(path)
        entries = []
        for b in blocks:
            key = digest(b)
            old = next((r for r in stored.get(rel, []) if r.get('block') == key), {})
            svg = local(wiki, old['svg']) if old.get('svg') else None
            valid = old.get('status') == 'pass' and svg and svg.is_file() and sha(svg) == old.get('svg_sha256')
            if execute and valid and old.get('renderer') != identity:
                valid = False
            if valid:
                record = old
            elif execute:
                record = {'block': key, 'section': b['section'], 'index': b['index'],
                          'renderer': identity, 'status': 'unverified', 'observed_at': datetime.now(timezone.utc).isoformat()}
                if executable:
                    base = local(wiki, '_meta/render/' + digest([rel, key]))
                    base.parent.mkdir(parents=True, exist_ok=True)
                    src, dest = base.with_suffix('.mmd'), base.with_suffix('.svg')
                    src.write_text(b['text'], encoding='utf-8')
                    if dest.exists():
                        dest.unlink()  # remove only our own stale renderer artifact
                    try:
                        result = subprocess.run([executable, '-i', str(src), '-o', str(dest)],
                                                capture_output=True, text=True, timeout=90)
                        ok = result.returncode == 0 and dest.is_file() and '<svg' in dest.read_text()
                        record.update(status='pass' if ok else 'fail', diagnostics=(result.stderr + result.stdout)[-6000:])
                        if ok:
                            record.update(svg=dest.relative_to(wiki).as_posix(), svg_sha256=sha(dest))
                    except subprocess.TimeoutExpired:
                        record.update(status='fail', diagnostics='renderer timed out after 90 seconds')
                else:
                    record['diagnostics'] = 'mmdc unavailable; render remains unverified'
            else:
                record = old
            entries.append(record)
            if not (record.get('status') == 'pass' and record.get('block') == key and
                    record.get('renderer') and record.get('svg')):
                issues.append(f"Mermaid not rendered/current: {rel} block {b['index']} {b['section']}")
            elif not execute and not valid:
                issues.append(f"Mermaid rendered artifact missing/changed: {rel} block {b['index']}")
        records[rel] = entries
    if execute:
        save(receipt_path, records)
    return issues
