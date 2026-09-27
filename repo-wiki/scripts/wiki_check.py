#!/usr/bin/env python3
"""Reference/freshness checks and recorded review gates; no automatic semantic proof."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_gates as gates
from urllib.parse import unquote, urlsplit

LINE = re.compile(r'L(\d+)(?:-L(\d+))?')
SKIP = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.cache'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def within(path, root):
    return path.resolve().is_relative_to(root.resolve())


def local(root, rel):
    p = root / rel
    if Path(rel).is_absolute() or not within(p, root):
        raise ValueError(f'path outside root: {rel}')
    return p


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, encoding='utf-8', delete=False) as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write('\n')
        temp = f.name
    os.replace(temp, path)


def load_plan(wiki):
    plan = read_json(local(wiki, '_meta/plan.json'))
    paths = [p['path'] for p in plan['pages']]
    if len(paths) != len(set(paths)):
        raise ValueError('duplicate page paths')
    for p in plan['pages']:
        local(wiki, p['path'])
        if not p.get('questions') or not p.get('sources') or not p.get('watch'):
            raise ValueError(f"missing questions/sources/watch: {p['path']}")
        for dep in p.get('depends_on', []):
            if dep not in paths or dep == p['path']:
                raise ValueError(f'invalid page dependency: {dep}')
    graph = {p['path']: p.get('depends_on', []) for p in plan['pages']}
    visited = set()
    def visit(key, active):
        if key in active:
            raise ValueError('cyclic page dependencies')
        if key not in visited:
            for dep in graph[key]:
                visit(dep, active | {key})
            visited.add(key)
    for key in graph:
        visit(key, set())
    return plan


def coverage_issues(plan, require_complete):
    """Validate declared coverage, not discover or judge the repository's knowledge."""
    issues = []
    if plan.get('schema_version') not in {4, 5, 6, 7}:
        return ['v4/v5/v6/v7 scope/coverage required; legacy checkpoints do not prove full coverage']
    scope, areas = plan.get('scope', {}), plan.get('coverage', [])
    if not isinstance(scope, dict) or not isinstance(areas, list):
        return ['scope must be an object and coverage a list']
    roots, exclusions = scope.get('roots', []), scope.get('user_exclusions', [])
    if not scope.get('request') or not roots or not areas:
        issues.append('requested scope, roots and coverage areas must be explicit')
    def path_ok(value):
        return (isinstance(value, str) and bool(value) and
                not Path(value).is_absolute() and '..' not in Path(value).parts)
    if not isinstance(roots, list) or not all(path_ok(r) for r in roots):
        return issues + ['roots must contain repository-relative paths']
    if not isinstance(exclusions, list) or not all(
            isinstance(e, dict) and path_ok(e.get('path')) and e.get('reason') for e in exclusions):
        return issues + ['user_exclusions require relative path and actual user reason']
    def under(path, parent):
        return Path(path).is_relative_to(Path(parent))
    page_map = {p['path']: p for p in plan['pages']}
    assigned, declared, names = set(), [], set()
    for area in areas:
        if not isinstance(area, dict):
            issues.append('coverage area must be an object'); continue
        name, paths = area.get('area'), area.get('paths', [])
        pages, gaps = area.get('pages', []), area.get('gaps', [])
        state = area.get('status')
        if not isinstance(name, str) or not name or name in names:
            issues.append('coverage area names must be nonempty and unique')
        if isinstance(name, str):
            names.add(name)
        if not isinstance(paths, list) or not paths or not all(path_ok(p) for p in paths):
            issues.append(f'{name}: missing or invalid paths'); continue
        declared.extend(paths)
        if any(not any(under(p, r) for r in roots) for p in paths):
            issues.append(f'{name}: paths outside requested roots')
        if not isinstance(pages, list) or not all(isinstance(p, str) for p in pages):
            issues.append(f'{name}: pages must be a list'); continue
        if not isinstance(gaps, list) or not all(isinstance(g, str) for g in gaps):
            issues.append(f'{name}: gaps must be a text list'); continue
        if state not in {'planned', 'partial', 'blocked', 'complete', 'excluded'}:
            issues.append(f'{name}: invalid coverage status')
        assigned.update(pages)
        for page in pages:
            if page not in page_map:
                issues.append(f'{name}: unknown page {page}')
        if state == 'excluded':
            if not all(any(under(p, e['path']) for e in exclusions) for p in paths):
                issues.append(f'{name}: exclusion has no matching user exclusion')
            if pages or gaps:
                issues.append(f'{name}: excluded areas cannot hide pages or pending gaps')
        else:
            if require_complete and state != 'complete':
                issues.append(f'{name}: unfinished ({state})')
            if state == 'complete' and (gaps or not pages):
                issues.append(f'{name}: complete requires pages and no gaps')
            if require_complete and gaps:
                issues.append(f'{name}: unresolved gaps: ' + '; '.join(gaps))
    for root in roots:
        if not any(under(p, root) for p in declared):
            issues.append(f'requested root has no coverage area: {root}')
    for path, page in page_map.items():
        if path not in assigned:
            issues.append(f'page not assigned to a coverage area: {path}')
        parent = page.get('parent')
        if parent is not None and (parent not in page_map or parent == path):
            issues.append(f'invalid parent: {path}')
        if not page.get('title') or page.get('kind') not in {'overview', 'design', 'flow', 'reference', 'guide'}:
            issues.append(f'page needs title and kind: {path}')
        if not page.get('sections'):
            issues.append(f'page needs an intended explanation outline: {path}')
        if plan.get('schema_version') in {5, 6, 7}:
            if not isinstance(page.get('objective'), str) or not page['objective'].strip():
                issues.append(f'page needs a reader outcome objective: {path}')
            questions = page.get('questions')
            if (not isinstance(questions, list) or not questions or
                    not all(isinstance(q, str) and q.strip() for q in questions) or
                    len(questions) != len(set(questions))):
                issues.append(f'page questions must be nonempty unique strings: {path}')
        if require_complete and page.get('next'):
            issues.append(f'page has unfinished action: {path}')
        seen, cursor = set(), path
        while cursor in page_map:
            if cursor in seen:
                issues.append(f'parent cycle containing {path}'); break
            seen.add(cursor)
            cursor = page_map[cursor].get('parent')
    if plan.get('schema_version') in {6, 7}:
        issues.extend(module_plan_issues(plan))
    return issues


def inspect_page(repo, wiki, page):
    path = local(wiki, page['path'])
    errors, refs = [], {}
    if not path.is_file():
        return [f"missing page: {page['path']}"], refs
    text = path.read_text(encoding='utf-8')
    # Remove fenced code: illustrative links there are not document citations.
    prose, fence = [], None
    for line in text.splitlines():
        m = re.match(r'^\s*(`{3,}|~{3,})', line)
        if m:
            mark = m.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence):
                fence = None
            continue
        if fence is None:
            prose.append(line)
    if fence is not None:
        errors.append('unclosed code fence')
    source_links = 0
    for label, raw in re.findall(r'\[([^\]\n]*)\]\((<[^>\n]+>|[^\s)]+)\)', '\n'.join(prose)):
        url = urlsplit(raw.strip('<>'))
        if url.scheme in {'http', 'https', 'mailto'}:
            continue
        if url.scheme or url.netloc:
            errors.append(f'unsupported local URL: {raw}')
            continue
        target = (path.parent / unquote(url.path)).resolve() if url.path else path
        if not (within(target, repo) or within(target, wiki)):
            errors.append(f'link outside repository/wiki: {raw}')
            continue
        if not target.exists():
            errors.append(f'missing link: {raw}')
            continue
        if within(target, repo) and not within(target, wiki) and target.is_file():
            key = target.relative_to(repo).as_posix()
            refs[key] = sha(target)
            source_links += 1
            match = LINE.fullmatch(url.fragment)
            display_range = re.search(r'\bL(\d+)(?:-L(\d+))?\b', label)
            if display_range and match and (display_range[1], display_range[2] or display_range[1]) != (match[1], match[2] or match[1]):
                errors.append(f'source label range differs from link target: {label} -> {raw}')
            if not match:
                errors.append(f'source link needs #Lstart-Lend: {raw}')
            else:
                try:
                    n = len(target.read_text(encoding='utf-8-sig').splitlines())
                    start, end = int(match[1]), int(match[2] or match[1])
                    if not 1 <= start <= end <= n:
                        errors.append(f'line range outside file: {raw} ({n} lines)')
                except UnicodeError:
                    errors.append(f'non-text source link: {raw}')
    if not source_links:
        errors.append('no local source range citations')
    return errors, refs


def inputs(repo, wiki, page, saved):
    repo, wiki = repo.resolve(), wiki.resolve()
    errors, refs = inspect_page(repo, wiki, page)
    files = {}
    for rel in sorted(set(page['sources'] + page['watch'] + list(refs))):
        path = local(repo, rel)
        if not path.exists():
            files[rel] = None  # deletion/missing dependency participates in freshness
            if rel in page['sources']:
                errors.append(f'missing required source: {rel}')
            continue
        candidates = path.rglob('*') if path.is_dir() else [path]
        files['watch:' + rel] = 'exists'
        for f in sorted(candidates):
            if any(part in SKIP for part in f.relative_to(repo).parts):
                continue
            if within(f, wiki):
                continue
            if f.is_symlink():
                # Fail explicitly instead of silently missing aliased source changes.
                errors.append(f'symlink input requires explicit resolved scope: {f.relative_to(repo)}')
                continue
            if f.is_file():
                files[f.relative_to(repo).as_posix()] = sha(f)
    for rel in page.get('cards', []):
        f = local(wiki, rel)
        if not f.is_file():
            errors.append(f'missing card: {rel}')
        files['card:' + rel] = sha(f) if f.is_file() else None
    path = local(wiki, page['path'])
    return errors, {'body': sha(path) if path.is_file() else None,
                    'inputs': files, 'task': page,
                    'dependencies': {d: hashlib.sha256(json.dumps(saved.get(d), sort_keys=True).encode()).hexdigest()
                                     for d in page.get('depends_on', [])}}


def inspect_all(repo, wiki, plan, saved):
    return {p['path']: inputs(repo, wiki, p, saved) for p in plan['pages']}


def freshness(plan, snapshots, saved):
    out = {}
    for page in plan['pages']:
        key = page['path']
        errors, now = snapshots[key]
        old = saved.get(key)
        reasons = []
        if errors:
            reasons.append('check_failed')
        if old is None:
            reasons.append('not_checkpointed')
        else:
            if old.get('review_pending'):
                reasons.append('review_rejected')
            if plan.get('schema_version') in {6, 7} and old.get('module_diagrams') != page_module_diagrams(plan, key):
                reasons.append('module_diagram_task_changed')
            for field in ('body', 'inputs', 'task', 'dependencies'):
                if old.get(field) != now[field]:
                    reasons.append({'body': 'page_edited', 'inputs': 'sources_or_cards_changed',
                                    'task': 'page_task_changed', 'dependencies': 'dependency_checkpoint_changed'}[field])
        out[key] = reasons
    changed = True
    while changed:
        changed = False
        for page in plan['pages']:
            if any(out[d] for d in page.get('depends_on', [])) and not out[page['path']]:
                out[page['path']] = ['dependency_needs_review']
                changed = True
    return out


REVIEW_CHECKS = {'task_assumptions', 'source_fidelity', 'explanation',
                 'examples', 'diagrams', 'scope_boundaries'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def text_ok(value):
    return isinstance(value, str) and bool(value.strip())


def repository_files(repo, wiki, roots):
    """A content inventory, not a claim that the agent read any of these files."""
    if not isinstance(roots, list) or not roots or not all(text_ok(r) for r in roots):
        raise ValueError('scope roots must be a nonempty path list')
    result = {}
    for rel in roots:
        root = local(repo, rel)
        if not root.exists():
            raise ValueError(f'missing scope root: {rel}')
        for f in root.rglob('*') if root.is_dir() else [root]:
            if any(p in SKIP for p in f.relative_to(repo).parts) or within(f, wiki):
                continue
            key = f.relative_to(repo).as_posix()
            if f.is_symlink():
                result[key] = 'symlink:' + os.readlink(f)
            elif f.is_file():
                result[key] = sha(f)
    return dict(sorted(result.items()))


def body_files(wiki):
    return {p.relative_to(wiki).as_posix(): sha(p) for p in sorted(wiki.rglob('*.md'))
            if '_meta' not in p.relative_to(wiki).parts}


def analysis_snapshot(repo, wiki, review):
    """Require an exhaustive reading ledger and module analysis before planning."""
    if not isinstance(review, dict) or review.get('open_findings') != []:
        raise ValueError('analysis requires an actual review with no unresolved reading/analysis findings')
    scope = review['scope']
    if not text_ok(scope.get('request')) or not isinstance(scope.get('user_exclusions'), list):
        raise ValueError('analysis scope requires request and user_exclusions')
    inventory = repository_files(repo, wiki, scope['roots'])
    modules = review.get('modules')
    if not isinstance(modules, list) or not modules:
        raise ValueError('analysis requires all discovered modules')
    ids, paths = set(), {}
    for m in modules:
        key = m['id']
        if not text_ok(key) or key in ids or not text_ok(m.get('name')) or not text_ok(m.get('summary')):
            raise ValueError('analysis modules need unique IDs, names and actual findings')
        if not isinstance(m.get('paths'), list) or not m['paths']:
            raise ValueError(f'module needs real scope paths: {key}')
        for rel in m['paths']:
            local(repo, rel)
            if not any(Path(rel).is_relative_to(Path(r)) for r in scope['roots']):
                raise ValueError(f'module path outside analysis scope: {rel}')
        ids.add(key); paths[key] = m['paths']
    files = review.get('files')
    if (not isinstance(files, list) or not all(isinstance(f, dict) for f in files) or
            sorted(f.get('path', '') for f in files) != sorted(inventory)):
        raise ValueError('reading ledger must classify every inventory file exactly once')
    assigned = set()
    for f in files:
        rel, state, members = f['path'], f.get('status'), f.get('modules', [])
        if not text_ok(f.get('evidence')) or not isinstance(members, list):
            raise ValueError(f'file needs actual reading/classification evidence: {rel}')
        if state == 'read':
            if not members or not all(m in ids for m in members):
                raise ValueError(f'read file needs discovered module ownership: {rel}')
            if inventory[rel].startswith('symlink:'):
                raise ValueError(f'read resolved symlink target in explicit scope: {rel}')
            if any(not any(Path(rel).is_relative_to(Path(p)) for p in paths[m]) for m in members):
                raise ValueError(f'file outside declared module paths: {rel}')
            assigned.update(members)
        elif state == 'nonsemantic':
            if members:
                raise ValueError(f'nonsemantic input cannot stand in for module reading: {rel}')
        elif state == 'user_excluded':
            if members or not any(text_ok(e.get('reason')) and
                                  Path(rel).is_relative_to(Path(e['path'])) for e in scope['user_exclusions']):
                raise ValueError(f'exclusion needs a matching actual user exclusion: {rel}')
        else:
            raise ValueError(f'unread or blocked input prevents completing analysis: {rel}')
    if assigned != ids:
        raise ValueError('every discovered module needs actually read source inputs')
    report = local(wiki, '_meta/overview.md')
    if not report.is_file() or not report.read_text(encoding='utf-8').strip():
        raise ValueError('write the whole-project analysis in _meta/overview.md first')
    if review.get('schema_version') == 7:
        gates.validate_reading(repo, wiki, review, inventory)
        gates.capability_analysis(repo, review, inventory)
        gates.resolve_findings(repo, wiki, 'analyze', None, review, inventory)
    return {'files': inventory, 'overview': sha(report)}


def module_plan_issues(plan):
    issues, seen, locations = [], set(), set()
    pages = {p['path'] for p in plan['pages']}
    modules = plan.get('modules')
    if not isinstance(modules, list) or not modules:
        return ['plan requires every analyzed module and its two diagram locations']
    for m in modules:
        if not isinstance(m, dict):
            issues.append('module must be an object'); continue
        key = m.get('id')
        if not text_ok(key) or key in seen:
            issues.append('module IDs must be nonempty and unique')
        if isinstance(key, str):
            seen.add(key)
        if not isinstance(m.get('pages'), list) or not m['pages'] or not all(p in pages for p in m['pages']):
            issues.append(f'{key}: module needs responsible planned pages'); continue
        diagrams = m.get('diagrams', {})
        if not isinstance(diagrams, dict):
            issues.append(f'{key}: diagrams must be an object'); continue
        for kind in ('call', 'sequence'):
            ref = diagrams.get(kind, {})
            if (not isinstance(ref, dict) or ref.get('page') not in m['pages'] or
                    not text_ok(ref.get('section')) or not re.match(r'^#{1,6} ', ref['section'])):
                issues.append(f'{key}: missing {kind} diagram page/heading'); continue
            loc = (ref['page'], ref['section'])
            if loc in locations:
                issues.append(f'{key}: each module diagram needs its own location')
            locations.add(loc)
    if plan.get('schema_version') == 7:
        issues.extend(gates.module_directory_issues(plan))
    return issues


def catalogue_digest(plan):
    # Progress fields change during writing, but the agreed task/catalogue does not.
    catalogue = json.loads(json.dumps(plan))
    for area in catalogue.get('coverage', []):
        for key in ('status', 'gaps'):
            area.pop(key, None)
    for page in catalogue.get('pages', []):
        page.pop('next', None)
    return digest(catalogue)


def page_module_diagrams(plan, page):
    return [{k: m.get(k) for k in ('id', 'name', 'paths', 'diagrams')}
            for m in plan.get('modules', []) if page in m.get('pages', [])]


def workflow_issues(repo, wiki, plan, require_plan=True):
    if plan.get('schema_version') not in {6, 7}:
        return ['v6/v7 require whole-project reading, analysis and a complete catalogue before writing']
    issues = []
    try:
        analysis = read_json(local(wiki, '_meta/analysis.json'))
        if analysis.get('review_pending'):
            issues.append('latest analysis rejected; resolve findings and analyze again')
        if analysis['snapshot'] != analysis_snapshot(repo, wiki, analysis['review']):
            issues.append('whole-project analysis stale: inventory, source content or overview changed')
        if analysis['review']['scope'] != plan['scope']:
            issues.append('plan scope differs from analyzed scope')
        expected = {m['id']: {k: m[k] for k in ('name', 'paths')} for m in analysis['review']['modules']}
        actual = {m['id']: {k: m[k] for k in ('name', 'paths')} for m in plan.get('modules', [])}
        if expected != actual:
            issues.append('catalogue must include exactly all analyzed modules and their paths')
        if plan.get('schema_version') == 7:
            issues.extend(gates.module_directory_issues(plan, wiki, check_files=require_plan))
            gates.validate_reading(repo, wiki, analysis['review'], analysis['snapshot']['files'])
            gates.capability_plan(wiki, plan, analysis)
            gates.require_recorded(wiki, 'analyze', 'analysis.json', analysis)
        if require_plan:
            sealed = read_json(local(wiki, '_meta/workflow.json'))
            if plan.get('schema_version') == 7:
                gates.require_recorded(wiki, 'plan', 'workflow.json', sealed)
            planning = local(wiki, '_meta/planning.md')
            if (sealed['analysis'] != digest(analysis) or sealed['catalogue'] != catalogue_digest(plan) or
                    sealed['planning'] != sha(planning)):
                issues.append('catalogue changed or analysis renewed; run plan before writing further')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        issues.append(f'missing or invalid analysis/catalogue checkpoint: {exc}')
    return issues


def mermaid_sections(path):
    """Associate real fenced blocks with their exact prose heading; ignore quoted examples."""
    result, section, fence, capture, lines = {}, None, None, False, []
    for line in path.read_text(encoding='utf-8').splitlines():
        if fence is None:
            heading = re.match(r'^#{1,6} ', line)
            opening = re.match(r'^\s*(`{3,}|~{3,})(.*)$', line)
            if heading:
                section = line.strip(); result.setdefault(section, [])
            elif opening:
                fence = opening[1]; capture = opening[2].strip().lower() == 'mermaid'; lines = []
        elif re.fullmatch(r'\s*' + re.escape(fence[0]) + '{' + str(len(fence)) + r',}\s*', line):
            if capture and section:
                result[section].append('\n'.join(lines))
            fence, capture = None, False
        elif capture:
            lines.append(line)
    return result


def diagram_issues(wiki, plan, saved=None, page=None):
    issues = module_plan_issues(plan)
    if issues:
        return issues
    for m in plan['modules']:
        for kind, ref in m['diagrams'].items():
            if kind not in {'call', 'sequence'} or (page and ref['page'] != page):
                continue
            path = local(wiki, ref['page'])
            blocks = mermaid_sections(path).get(ref['section'], []) if path.is_file() else []
            expected = r'(?:flowchart|graph)\s+(?:TB|TD|BT|LR|RL)\b' if kind == 'call' else r'sequenceDiagram\b'
            valid = False
            for block in blocks:
                rows = [s.strip() for s in block.splitlines() if s.strip() and not s.lstrip().startswith('%%')]
                if len(rows) >= 2 and re.match(expected, rows[0]):
                    # Participant declarations alone do not describe any sequence.
                    valid = (kind == 'call' or any(
                        re.match(r'Note\s+(?:over|left of|right of)\s+.+:\s*\S', row) or
                        re.match(r'[^:\s]+(?:>|x|\))[^:]*:\s*\S', row)
                        for row in rows[1:]))
                    if valid:
                        break
            if not valid:
                issues.append(f"{m['id']}: missing nonempty {kind} Mermaid at {ref['page']} {ref['section']}")
            if saved is not None:
                check = saved.get(ref['page'], {}).get('review', {}).get('checks', {}).get('diagrams', {})
                if check.get('status') != 'pass':
                    issues.append(f"{m['id']}: required module diagrams cannot be not_applicable or unreviewed")
    return issues


def headings(path):
    """Exact Markdown heading lines outside code fences, not inferred slugs."""
    result, fence = set(), None
    for line in path.read_text(encoding='utf-8').splitlines():
        mark = re.match(r'^\s*(`{3,}|~{3,})', line)
        if mark:
            token = mark[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
        elif fence is None and re.match(r'^#{1,6} ', line):
            result.add(line.strip())
    return result


def review_issues(wiki, page, review, snapshot):
    """Validate traceable review records; a real reader must judge their truth."""
    if not isinstance(review, dict):
        return ['missing page review; mechanical checkpoint is not content acceptance']
    issues = []
    if review.get('open_findings') != []:
        issues.append('page review must explicitly have no open findings')
    answers = review.get('answers')
    if not isinstance(answers, list):
        return issues + ['review answers must be a list']
    locations = headings(local(wiki, page['path'])) if snapshot['body'] else set()
    seen = []
    for answer in answers:
        if not isinstance(answer, dict):
            issues.append('answer must be an object'); continue
        q = answer.get('question')
        if q not in page['questions']:
            issues.append(f'review contains unplanned question: {q}')
        seen.append(q)
        if answer.get('section') not in locations:
            issues.append(f'answer heading missing from prose: {q}')
        if not text_ok(answer.get('conclusion')):
            issues.append(f'answer needs an actual review conclusion: {q}')
        sources = answer.get('sources')
        if (not isinstance(sources, list) or not sources or
                not all(isinstance(s, str) and s in snapshot['inputs'] and
                        not s.startswith(('watch:', 'card:')) and snapshot['inputs'][s]
                        for s in sources)):
            issues.append(f'answer evidence must name captured repository input files: {q}')
    if sorted(str(q) for q in seen) != sorted(page['questions']):
        issues.append('review must answer every planned question exactly once')
    checks = review.get('checks', {})
    if not isinstance(checks, dict):
        return issues + ['review checks must be an object']
    for name in sorted(REVIEW_CHECKS):
        check = checks.get(name, {})
        allowed = {'pass', 'not_applicable'} if name in {'examples', 'diagrams'} else {'pass'}
        if (not isinstance(check, dict) or check.get('status') not in allowed or
                not text_ok(check.get('evidence'))):
            issues.append(f'review check needs a supported result and concrete evidence: {name}')
    return issues


def scope_inventory(repo, wiki, plan):
    """File membership detects newly added modules outside existing page watches."""
    result = set()
    for root in plan['scope']['roots']:
        path = local(repo, root)
        if not path.exists():
            raise ValueError(f'missing requested scope root: {root}')
        for f in path.rglob('*') if path.is_dir() else [path]:
            rel = f.relative_to(repo)
            if any(part in SKIP for part in rel.parts) or within(f, wiki):
                continue
            if f.is_symlink():
                result.add(rel.as_posix() + ' -> ' + os.readlink(f))
            elif f.is_file():
                result.add(rel.as_posix())
    return sorted(result)


def scope_review_snapshot(repo, wiki, plan, saved, review):
    if not isinstance(review, dict):
        raise ValueError('missing whole-scope review')
    if review.get('open_findings') != [] or not text_ok(review.get('cross_page_checks')):
        raise ValueError('scope review requires cross-page conclusions and no open findings')
    areas = review.get('areas')
    expected = {a['area']: a for a in plan['coverage'] if a['status'] != 'excluded'}
    if (not isinstance(areas, list) or not all(isinstance(a, dict) for a in areas) or
            sorted(str(a.get('area')) for a in areas) != sorted(expected)):
        raise ValueError('scope review must assess every non-excluded area exactly once')
    for a in areas:
        if (not text_ok(a.get('assessment')) or not isinstance(a.get('pages'), list) or
                sorted(a['pages']) != sorted(expected[a['area']]['pages'])):
            raise ValueError(f"scope review needs all responsible pages and a conclusion: {a['area']}")
    sources = review.get('discovery_sources')
    if not isinstance(sources, list) or not sources or not all(text_ok(s) for s in sources):
        raise ValueError('scope review requires real discovery source files')
    discovery = {}
    for rel in sources:
        path = local(repo, rel)
        if not path.is_file() or within(path, wiki):
            raise ValueError(f'discovery source must be a repository input file: {rel}')
        discovery[rel] = sha(path)
    if plan.get('schema_version') == 7:
        gates.scope_capabilities(repo, wiki, plan, review, repository_files(repo, wiki, plan['scope']['roots']))
    result = {'plan': sha(local(wiki, '_meta/plan.json')), 'checkpoints': digest(saved),
              'inventory': scope_inventory(repo, wiki, plan), 'discovery_inputs': discovery}
    if plan.get('schema_version') in {6, 7}:
        result['workflow'] = sha(local(wiki, '_meta/workflow.json'))
    if plan.get('schema_version') == 7:
        result['wiki_bodies'] = body_files(wiki)
    return result


def acceptance_issues(wiki, plan, snapshots, saved, repo=None):
    if plan.get('schema_version') not in {5, 6, 7}:
        return {'schema': ['v5/v6/v7 plan and real content reviews required; migrate without rewriting valid pages']}
    result = {}
    for page in plan['pages']:
        issues = review_issues(wiki, page, saved.get(page['path'], {}).get('review'), snapshots[page['path']][1])
        if plan.get('schema_version') == 7 and not issues:
            try:
                gates.review_evidence(repo, wiki, plan, page, saved.get(page['path'], {}).get('review'), snapshots[page['path']][1])
                gates.require_recorded(wiki, 'checkpoint', 'state.json', saved.get(page['path']), page['path'])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                issues.append(str(exc))
        if issues:
            result[page['path']] = issues
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command', choices=['inventory', 'read', 'render', 'analyze', 'plan', 'check', 'status', 'checkpoint', 'scope-review', 'finish'])
    ap.add_argument('--repo', type=Path, required=True)
    ap.add_argument('--wiki', type=Path, required=True)
    ap.add_argument('--page')
    ap.add_argument('--accept-edits', action='store_true')
    ap.add_argument('--root', action='append', help='Repository-relative scope root for inventory; repeat as needed')
    ap.add_argument('--reuse-existing', action='store_true', help='Analyze existing documentation for migration/update; preserve its baseline')
    ap.add_argument('--review-file', type=Path, help='Actual page or scope review; never synthesized from counters')
    ap.add_argument('--source', help='Repository-relative UTF-8 source for read')
    ap.add_argument('--start-line', type=int)
    ap.add_argument('--end-line', type=int)
    ap.add_argument('--renderer', help='mmdc executable path; render only')
    ap.add_argument('--reason', help='Concrete migration/update reason; required by reuse-existing')
    args = ap.parse_args()
    global AUDIT_ARGS, AUDIT_ATTEMPT
    if args.command in {'analyze', 'plan', 'checkpoint', 'scope-review'}:
        AUDIT_ARGS = args
        AUDIT_ATTEMPT = gates.begin_attempt(args)
    repo, wiki = args.repo.resolve(), args.wiki.resolve()
    if args.command in {'inventory', 'analyze', 'plan', 'scope-review', 'finish'} and args.page:
        raise ValueError('this command applies to the whole requested scope; omit --page')
    if args.review_file and args.command not in {'analyze', 'checkpoint', 'scope-review'}:
        raise ValueError('--review-file is only used by analyze/checkpoint/scope-review')
    if args.root and args.command != 'inventory':
        raise ValueError('--root is only used by inventory')
    if args.reuse_existing and args.command != 'analyze':
        raise ValueError('--reuse-existing is only used by analyze')
    if args.command == 'read':
        if not args.source:
            raise ValueError('read requires --source; consume its displayed source before recording findings')
        return gates.read_source(repo, wiki, args.source, args.start_line, args.end_line)
    if args.command == 'inventory':
        print(json.dumps({'roots': args.root or ['.'], 'files': repository_files(repo, wiki, args.root or ['.']),
                          'reading_status': 'inventory_only_not_read'}, ensure_ascii=False, indent=2))
        return 0
    if args.command == 'analyze':
        if not args.review_file:
            raise ValueError('analyze requires the actual whole-project reading/analysis review')
        review = read_json(args.review_file)
        path = local(wiki, '_meta/analysis.json')
        try:
            if review.get('schema_version') == 7 and args.reuse_existing and not text_ok(args.reason):
                raise ValueError('--reuse-existing requires --reason; previous chronology remains recorded')
            snapshot = analysis_snapshot(repo, wiki, review)
            existing = body_files(wiki)
            if existing and not args.reuse_existing:
                raise ValueError('body already exists before analysis; preserve it and explicitly use --reuse-existing for migration/update')
        except (ValueError, KeyError, TypeError) as exc:
            if path.exists():
                previous = read_json(path)
                previous['review_pending'] = str(exc)
                save(path, previous)
            raise
        save(path, {'review': review, 'snapshot': snapshot, 'existing_pages': existing,
                    'mode': 'reuse_existing' if args.reuse_existing else 'new', 'reason': args.reason})
        print(json.dumps({'analysis_recorded': True, 'files': len(snapshot['files']),
                          'modules': len(review['modules']), 'next': 'plan the full catalogue before writing'}))
        return 0
    plan = load_plan(wiki)
    if args.command == 'plan':
        issues = coverage_issues(plan, require_complete=False)
        if plan.get('schema_version') in {6, 7} and not issues:
            issues.extend(workflow_issues(repo, wiki, plan, require_plan=False))
            planning = local(wiki, '_meta/planning.md')
            if not planning.is_file() or not planning.read_text(encoding='utf-8').strip():
                issues.append('write the full hierarchy and module allocation in _meta/planning.md first')
            analysis = read_json(local(wiki, '_meta/analysis.json')) if not issues else None
            if analysis and not local(wiki, '_meta/workflow.json').exists() and body_files(wiki) != analysis['existing_pages']:
                issues.append('body written or changed before the first complete catalogue checkpoint')
            if not issues:
                save(local(wiki, '_meta/workflow.json'), {'analysis': digest(analysis),
                     'catalogue': catalogue_digest(plan), 'planning': sha(planning),
                     'body_at_plan': body_files(wiki), 'analysis_mode': analysis['mode']})
        print(json.dumps({'plan_issues': issues, 'semantic_coverage': 'agent_must_check_repository'}, ensure_ascii=False, indent=2))
        return int(bool(issues))
    selected = [p for p in plan['pages'] if not args.page or p['path'] == args.page]
    if not selected:
        raise ValueError('unknown page')
    if args.command == 'render':
        issues = gates.rendering(wiki, selected if args.page else gates.render_pages(wiki, selected), execute=True, renderer=args.renderer)
        print(json.dumps({'render_issues': issues}, ensure_ascii=False, indent=2))
        return int(bool(issues))
    state_path = local(wiki, '_meta/state.json')
    saved = read_json(state_path) if state_path.exists() else {}
    if args.command in {'scope-review', 'finish'}:
        issues = coverage_issues(plan, require_complete=True)
        phases = workflow_issues(repo, wiki, plan)
        if plan.get('schema_version') != 7:
            phases.append('v7 delivery requires full reading receipts, capabilities, rendered diagrams and evidence reviews; migrate legacy state')
        else:
            try:
                gates.capability_plan(wiki, plan, read_json(local(wiki, '_meta/analysis.json')), require_body=True)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                phases.append(str(exc))
        diagrams = diagram_issues(wiki, plan, saved) if plan.get('schema_version') in {6, 7} else ['v6 module call/sequence diagrams required']
        if plan.get('schema_version') == 7:
            diagrams.extend(gates.rendering(wiki, gates.render_pages(wiki, plan['pages'])))
        snapshots = inspect_all(repo, wiki, plan, saved)
        statuses = freshness(plan, snapshots, saved)
        pending = {key: value for key, value in statuses.items() if value}
        reviews = acceptance_issues(wiki, plan, snapshots, saved, repo)
        scope_issues = []
        scope_path = local(wiki, '_meta/scope-review.json')
        if args.command == 'scope-review':
            if issues or pending or reviews or phases or diagrams:
                print(json.dumps({'coverage_issues': issues, 'pages_needing_review': pending,
                                  'content_review_issues': reviews, 'workflow_issues': phases,
                                  'diagram_issues': diagrams}, ensure_ascii=False, indent=2))
                return 1
            if not args.review_file:
                raise ValueError('scope-review requires --review-file from actual repository reconciliation')
            review = read_json(args.review_file)
            try:
                snapshot = scope_review_snapshot(repo, wiki, plan, saved, review)
            except ValueError as exc:
                if scope_path.exists():
                    previous = read_json(scope_path)
                    previous['review_pending'] = {'review': review, 'error': str(exc)}
                    save(scope_path, previous)
                raise
            save(scope_path, {'review': review, 'snapshot': snapshot})
            print(json.dumps({'scope_review_recorded': True, 'inventory_files': len(snapshot['inventory']),
                              'semantic_validation': 'recorded_agent_review_not_independent_proof'}))
            return 0
        if not scope_path.exists():
            scope_issues.append('missing whole-scope review; run scope-review after actual reconciliation')
        elif not issues and not reviews:
            stored = read_json(scope_path)
            if stored.get('review_pending'):
                scope_issues.append('latest scope review rejected; resolve findings and review again')
            try:
                if plan.get('schema_version') == 7:
                    gates.require_recorded(wiki, 'scope-review', 'scope-review.json', stored)
                if stored.get('snapshot') != scope_review_snapshot(repo, wiki, plan, saved, stored.get('review')):
                    scope_issues.append('scope review stale: plan, checkpoints, discovery inputs or file membership changed')
            except ValueError as exc:
                scope_issues.append(str(exc))
        complete = not (issues or pending or reviews or scope_issues or phases or diagrams)
        print(json.dumps({'coverage_issues': issues, 'pages_needing_review': pending,
                          'content_review_issues': reviews, 'scope_review_issues': scope_issues,
                          'workflow_issues': phases, 'diagram_issues': diagrams,
                          'declared_scope_and_files_complete': not issues and not pending,
                          'ready_for_delivery': complete,
                          'content_quality': 'recorded_agent_review_not_independent_proof'}, ensure_ascii=False, indent=2))
        return int(not complete)
    if args.command == 'checkpoint':
        if not args.page:
            raise ValueError('checkpoint requires --page; review pages individually')
        page = selected[0]
        if plan.get('schema_version') in {6, 7}:
            phases = coverage_issues(plan, require_complete=False) + workflow_issues(repo, wiki, plan)
            if phases:
                print(json.dumps({'workflow_issues': phases}, ensure_ascii=False)); return 1
        if page.get('next'):
            raise ValueError('unresolved next action; keep as draft')
        errors, now = inputs(repo, wiki, page, saved)
        if errors:
            print(json.dumps({'errors': errors}, ensure_ascii=False)); return 1
        if plan.get('schema_version') in {5, 6, 7}:
            if not args.review_file:
                raise ValueError('v5/v6/v7 checkpoint requires --review-file from actual reader/source review')
            review = read_json(args.review_file)
            errors = review_issues(wiki, page, review, now)
            if plan.get('schema_version') in {6, 7}:
                errors.extend(diagram_issues(wiki, plan, {args.page: {'review': review}}, page=args.page))
            if errors:
                if args.page in saved:
                    saved[args.page]['review_pending'] = {'review': review, 'issues': errors}
                    save(state_path, saved)
                print(json.dumps({'content_review_issues': errors}, ensure_ascii=False)); return 1
            if plan.get('schema_version') == 7:
                try:
                    gates.review_evidence(repo, wiki, plan, page, review, now)
                    errors.extend(gates.rendering(wiki, [page]))
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    errors.append(str(exc))
                if errors:
                    if args.page in saved:
                        saved[args.page]['review_pending'] = {'review': review, 'issues': errors}
                        save(state_path, saved)
                    print(json.dumps({'content_review_issues': errors}, ensure_ascii=False)); return 1
            now['review'] = review
            if plan.get('schema_version') in {6, 7}:
                now['module_diagrams'] = page_module_diagrams(plan, args.page)
        if page.get('depends_on'):
            all_now = inspect_all(repo, wiki, plan, saved)
            states = freshness(plan, all_now, saved)
            if any(states[d] for d in page['depends_on']):
                raise ValueError('checkpoint dependencies first')
        old = saved.get(args.page)
        if old and old['body'] != now['body'] and not args.accept_edits:
            raise ValueError('page changed; inspect and preserve edits before --accept-edits')
        saved[args.page] = now
        save(state_path, saved)
        print(json.dumps({'checkpointed': args.page, 'semantic_validation': 'agent_responsibility'}))
        return 0
    snapshots = inspect_all(repo, wiki, plan if args.command == 'status' else {'pages': selected}, saved)
    if args.command == 'status':
        statuses = freshness(plan, snapshots, saved)
        result = {p['path']: statuses[p['path']] or ['current_checkpoint'] for p in selected}
    else:
        result = {p['path']: snapshots[p['path']][0] for p in selected if snapshots[p['path']][0]}
    diagrams = []
    phases = []
    if plan.get('schema_version') in {6, 7}:
        phases = workflow_issues(repo, wiki, plan)
        if args.command == 'check':
            diagrams = diagram_issues(wiki, plan, page=args.page)
            if plan.get('schema_version') == 7:
                diagrams.extend(gates.rendering(wiki, selected if args.page else gates.render_pages(wiki, selected)))
    print(json.dumps({'pages': len(selected), 'results': result, 'workflow_issues': phases,
                      'diagram_issues': diagrams}, ensure_ascii=False, indent=2))
    return int(bool(phases or diagrams) or any(snapshots[p['path']][0] for p in selected))


AUDIT_ARGS = AUDIT_ATTEMPT = None

if __name__ == '__main__':
    error = None
    try:
        code = main()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        error = str(exc)
        print(json.dumps({'error': error}, ensure_ascii=False))
        code = 2
    finally:
        if AUDIT_ATTEMPT:
            gates.end_attempt(AUDIT_ARGS, AUDIT_ATTEMPT, locals().get('code', 2), error)
    raise SystemExit(code)
