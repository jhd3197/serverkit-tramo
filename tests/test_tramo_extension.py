"""serverkit-tramo (Automations) extension tests.

Moved out of the ServerKit repo along with the extension (the extension now
lives in its own repository and ships as a runtime-ESM bundle). ``_load_ext``
registers this repo's ``backend/`` as the dashed package
``app.plugins.serverkit-tramo`` — mirroring how the panel loads an installed
extension's backend at boot (the same shape production's
``plugin_service._ensure_builtin_backend_importable`` produced for the
builtin). The models module is imported at module top so its
``ext_serverkit_tramo_*`` tables register on ``db.metadata`` before the
``app`` fixture runs ``db.create_all()``.

Docker and the tramo HTTP API are mocked at the two service choke-points
(``TramoHostService._docker`` / ``._api``) so nothing shells out or talks HTTP.
Cross-platform: tests that exercise the ``os.name == 'nt'`` gate force it
explicitly so they behave the same on the Windows dev box and Linux CI.

Also covers plan 45 Phase 4: the retired ``/api/v1/workflows`` routes are gone,
the four ported event emitters reach EventService, ``app.stopped`` is no longer
double-emitted by docker_service, and the admin-only legacy export.

These tests still need the panel's Flask app + fixtures, so run them from a
ServerKit checkout — see tests/README.md.
"""
import importlib
import importlib.util
import json
import os
import sys
from types import SimpleNamespace

import pytest

from app.services import plugin_service

SLUG = 'serverkit-tramo'
# realpath so a symlinked copy inside <panel>/backend/tests still resolves back
# to this repository root. SERVERKIT_TRAMO_DIR overrides when copied (not linked).
EXT_DIR = os.environ.get(
    'SERVERKIT_TRAMO_DIR',
    os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
)


def _load_ext():
    """Register this repo's backend/ as ``app.plugins.<slug>`` — mirrors how the
    panel loads an installed extension's backend at boot."""
    backend_dir = os.path.join(EXT_DIR, 'backend')
    assert os.path.isdir(backend_dir), f'extension backend not found at {backend_dir}'
    spec = importlib.util.spec_from_file_location(
        f'app.plugins.{SLUG}',
        os.path.join(backend_dir, '__init__.py'),
        submodule_search_locations=[backend_dir],
    )
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[f'app.plugins.{SLUG}'] = pkg
    spec.loader.exec_module(pkg)
    mods = {}
    for name in ('models', 'host_service', 'workflow_store', 'events_bridge',
                 'run_sync', 'jobs', 'templates', 'lifecycle', 'tramo'):
        mods[name] = importlib.import_module(f'app.plugins.{SLUG}.{name}')
    return mods


_M = _load_ext()
models_mod = _M['models']
host_mod = _M['host_service']
store_mod = _M['workflow_store']
eb_mod = _M['events_bridge']
run_sync_mod = _M['run_sync']
jobs_mod = _M['jobs']
templates_mod = _M['templates']
bp_mod = _M['tramo']

TramoWorkflow = models_mod.TramoWorkflow
TramoRun = models_mod.TramoRun
TramoHostService = host_mod.TramoHostService
WorkflowStore = store_mod.WorkflowStore


# --------------------------------------------------------------------------- #
# helpers / fixtures
# --------------------------------------------------------------------------- #
def _mk_plugin_row(config=None):
    from app import db
    from app.models.plugin import InstalledPlugin
    row = InstalledPlugin(
        name=SLUG, display_name='Automations', slug=SLUG, version='1.0.0',
        status=InstalledPlugin.STATUS_ACTIVE,
    )
    row.config = config or {}
    db.session.add(row)
    db.session.commit()
    return row


def _mk_admin():
    from app import db
    from app.models.user import User
    from werkzeug.security import generate_password_hash
    u = User(email='tramoadmin@t.local', username='tramoadmin',
             password_hash=generate_password_hash('x'),
             role=User.ROLE_ADMIN, is_active=True)
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def posix(monkeypatch):
    """Force the Linux path through the host service's Windows gate.

    Patches the ``_is_windows`` seam (never the global ``os.name`` -- that would
    swap ``pathlib`` to ``PosixPath`` and crash on the Windows dev box).
    """
    monkeypatch.setattr(TramoHostService, '_is_windows', classmethod(lambda cls: False))
    return True


@pytest.fixture
def tramo_client(app):
    if 'tramo' not in app.blueprints:
        app.register_blueprint(bp_mod.tramo_bp, url_prefix='/api/v1/tramo')
    return app.test_client()


# --------------------------------------------------------------------------- #
# manifest
# --------------------------------------------------------------------------- #
def _manifest():
    with open(os.path.join(EXT_DIR, 'plugin.json'), encoding='utf-8') as f:
        return json.load(f)


def test_manifest_passes_validator():
    m = _manifest()
    assert plugin_service._validate_manifest(m) is True
    assert m['name'] == SLUG
    assert m['entry_point'] == 'tramo:tramo_bp'
    assert m['url_prefix'] == '/api/v1/tramo'
    assert m['models'] == 'models:register'
    nav = m['contributions']['nav'][0]
    assert nav['route'] == '/automations' and nav['id'] == 'automations'
    assert m['contributions']['page_titles']['/automations'] == 'Automations'
    # sdk_version drives the runtime SDK gate; it must satisfy the panel's SDK.
    from app.utils.sdk import SDK_VERSION, sdk_version_satisfies
    assert m['sdk_version']
    assert sdk_version_satisfies(m['sdk_version'], SDK_VERSION)
    # Runtime-ESM bundle, loaded by the no-rebuild frontend loader.
    assert m['frontend_entry'] == 'dist/index.mjs'


def test_manifest_permissions_known_and_no_dashes():
    from app.plugins_sdk import permissions as sdk_perms
    m = _manifest()
    assert sdk_perms.unknown_permissions(m['permissions']) == []
    assert '—' not in m['description'] and '–' not in m['description']


def test_lifecycle_and_job_refs_resolve():
    m = _manifest()
    for ref in m['lifecycle'].values():
        module_name, func_name = ref.split(':')
        mod = importlib.import_module(f'app.plugins.{SLUG}.{module_name}')
        assert callable(getattr(mod, func_name, None)), ref
    for job in m['jobs']:
        module_name, func_name = job['handler'].split(':')
        mod = importlib.import_module(f'app.plugins.{SLUG}.{module_name}')
        assert callable(getattr(mod, func_name, None)), job['handler']


def test_entry_point_resolves_to_blueprint():
    assert getattr(bp_mod, 'tramo_bp', None) is not None
    assert bp_mod.tramo_bp.name == 'tramo'


def test_frontend_exports_route_components():
    """Every `component` value in the manifest's route contributions must be a
    named export of the runtime entry (resolveComponent matches them)."""
    with open(os.path.join(EXT_DIR, 'frontend', 'runtime-entry.jsx'), encoding='utf-8') as f:
        src = f.read()
    m = _manifest()
    for route in m['contributions']['routes']:
        assert route['component'] in src, route['component']


# --------------------------------------------------------------------------- #
# models + purge
# --------------------------------------------------------------------------- #
def test_models_register_and_tables_exist(app):
    from app import db
    from sqlalchemy import inspect
    assert set(models_mod.register(db)) == {TramoWorkflow, TramoRun}
    tables = [t for t in inspect(db.engine).get_table_names()
              if t.startswith('ext_serverkit_tramo')]
    assert 'ext_serverkit_tramo_workflows' in tables
    assert 'ext_serverkit_tramo_runs' in tables


def test_purge_drops_only_prefixed_tables(app):
    from app import db
    from app.services import extension_lifecycle
    from sqlalchemy import inspect
    plugin = SimpleNamespace(slug=SLUG)
    dropped = extension_lifecycle.purge_models(plugin)
    assert dropped >= 2
    remaining = [t for t in inspect(db.engine).get_table_names()
                 if t.startswith('ext_serverkit_tramo')]
    assert remaining == []
    # A core table must survive.
    assert 'users' in inspect(db.engine).get_table_names()
    db.create_all()  # restore for later tests in this module


# --------------------------------------------------------------------------- #
# workflow store CRUD + slug + materialize + deploy
# --------------------------------------------------------------------------- #
def test_create_slugifies_and_uniquifies(app):
    a = WorkflowStore.create('My Flow!')
    b = WorkflowStore.create('My Flow!')
    assert a.slug == 'my-flow'
    assert b.slug == 'my-flow-2'
    assert a.get_doc().get('nodes') == []


def test_create_doc_has_meta_and_version(app):
    """A brand-new workflow doc must carry `meta` (and `version`): the editor's
    Canvas reads `doc.meta.mcpServers` unconditionally and crashes without it."""
    doc = WorkflowStore.create('needs-meta').get_doc()
    assert doc.get('meta') == {}
    assert doc.get('version') == 1


def test_create_rejects_blank_name(app):
    with pytest.raises(ValueError):
        WorkflowStore.create('   ')


def test_update_bumps_doc_version_and_dirty(app):
    wf = WorkflowStore.create('flow')
    assert wf.doc_version == 1
    WorkflowStore.update(wf.slug, doc={'nodes': [{'id': 'n1'}], 'edges': []})
    assert wf.doc_version == 2
    # Never deployed + enabled => dirty.
    assert wf.is_dirty() is True


def test_delete_removes_row(app):
    wf = WorkflowStore.create('gone')
    WorkflowStore.delete(wf.slug)
    assert WorkflowStore.get('gone') is None


def test_materialize_writes_only_enabled(app, monkeypatch, posix):
    on = WorkflowStore.create('on-flow', enabled=True)
    WorkflowStore.create('off-flow', enabled=False)
    written = {}
    removed = []
    monkeypatch.setattr(WorkflowStore, '_write_file',
                        classmethod(lambda cls, slug, doc: written.__setitem__(slug, doc)))
    monkeypatch.setattr(WorkflowStore, '_list_files',
                        classmethod(lambda cls: ['on-flow', 'stale-flow']))
    monkeypatch.setattr(WorkflowStore, '_remove_file',
                        classmethod(lambda cls, slug: removed.append(slug)))
    summary = WorkflowStore.materialize()
    assert summary['written'] == ['on-flow']
    assert 'on-flow' in written and 'off-flow' not in written
    # stale + disabled files pruned.
    assert 'stale-flow' in removed


def test_deploy_stamps_deployed_at(app, monkeypatch, posix):
    wf = WorkflowStore.create('dep')
    monkeypatch.setattr(TramoHostService, 'is_installed', classmethod(lambda cls: True))
    monkeypatch.setattr(WorkflowStore, 'materialize',
                        classmethod(lambda cls: {'written': ['dep'], 'pruned': []}))
    monkeypatch.setattr(TramoHostService, 'control',
                        classmethod(lambda cls, action: {'success': True}))
    res = WorkflowStore.deploy()
    assert res['success'] is True
    assert wf.deployed_at is not None
    assert wf.is_dirty() is False


def test_deploy_requires_installed_engine(app, monkeypatch):
    monkeypatch.setattr(TramoHostService, 'is_installed', classmethod(lambda cls: False))
    res = WorkflowStore.deploy()
    assert res['success'] is False
    assert 'not installed' in res['error']


# --------------------------------------------------------------------------- #
# host service: argv, control, status, nt guard
# --------------------------------------------------------------------------- #
def test_build_run_args_argv(app):
    argv = TramoHostService._build_run_args(8377, 'SECRETKEY', callback_api_key='CBKEY')
    joined = ' '.join(argv)
    assert argv[0] == 'run' and '-d' in argv
    assert '127.0.0.1:8377:3000' in argv           # loopback publish only
    assert f'{host_mod.HOST_WORKFLOWS_DIR}:/workflows' in argv
    assert f'{host_mod.HOST_STATE_DIR}:/state' in argv
    assert 'TRAMO_API_KEY=SECRETKEY' in argv
    assert 'TRAMO_PACKS=all' in argv
    assert 'SERVERKIT_API_KEY=CBKEY' in argv
    assert any(a.startswith('SERVERKIT_URL=') for a in argv)
    assert 'host.docker.internal:host-gateway' in argv
    assert argv[-1] == host_mod.IMAGE
    assert 'ghcr.io/jhd3197/tramo-server:0.1.1' == host_mod.IMAGE


def test_build_run_args_includes_pack_secrets(app, monkeypatch):
    _mk_plugin_row()
    TramoHostService.set_pack_secrets({'TELEGRAM_BOT_TOKEN': 'abc123'})
    argv = TramoHostService._build_run_args(8377, 'KEY')
    assert 'TELEGRAM_BOT_TOKEN=abc123' in argv


def test_pack_secrets_round_trip_encrypted(app):
    _mk_plugin_row()
    TramoHostService.set_pack_secrets({'GMAIL_OAUTH_TOKEN': 'tok'})
    # Stored value must not be the plaintext (when encryption is configured).
    from app.utils.crypto import is_encryption_configured
    raw = TramoHostService._config().get('pack_secrets', {}).get('GMAIL_OAUTH_TOKEN')
    if is_encryption_configured():
        assert raw != 'tok'
    assert TramoHostService.get_pack_secrets()['GMAIL_OAUTH_TOKEN'] == 'tok'


def test_set_pack_secret_empty_value_deletes(app):
    _mk_plugin_row()
    TramoHostService.set_pack_secrets({'X_TOKEN': 'v'})
    names = TramoHostService.set_pack_secrets({'X_TOKEN': ''})
    assert 'X_TOKEN' not in names


def test_control_maps_actions(app, monkeypatch, posix):
    calls = []
    monkeypatch.setattr(TramoHostService, 'is_installed', classmethod(lambda cls: True))
    monkeypatch.setattr(TramoHostService, '_docker',
                        classmethod(lambda cls, args, **kw: calls.append(args) or {'success': True}))
    for action in ('start', 'stop', 'restart'):
        res = TramoHostService.control(action)
        assert res['success'] and res['action'] == action
    assert calls[0] == ['start', host_mod.CONTAINER_NAME]
    assert calls[2] == ['restart', host_mod.CONTAINER_NAME]


def test_control_rejects_bad_action(app):
    assert TramoHostService.control('nuke')['success'] is False


def test_status_states(app, monkeypatch, posix):
    # not installed
    monkeypatch.setattr(TramoHostService, '_docker',
                        classmethod(lambda cls, args, **kw: {'success': False}))
    assert TramoHostService.get_status()['state'] == 'not_installed'

    # stopped
    monkeypatch.setattr(TramoHostService, '_docker',
                        classmethod(lambda cls, args, **kw: {'success': True, 'stdout': 'false'}))
    assert TramoHostService.get_status()['state'] == 'stopped'

    # running + unhealthy
    monkeypatch.setattr(TramoHostService, '_docker',
                        classmethod(lambda cls, args, **kw: {'success': True, 'stdout': 'true'}))
    monkeypatch.setattr(TramoHostService, '_api',
                        classmethod(lambda cls, m, p, payload=None, timeout=None: {'success': False, 'error': 'x'}))
    assert TramoHostService.get_status()['state'] == 'unhealthy'

    # running + ready
    monkeypatch.setattr(TramoHostService, '_api',
                        classmethod(lambda cls, m, p, payload=None, timeout=None: {'success': True, 'data': {'version': '0.1.1'}}))
    st = TramoHostService.get_status()
    assert st['state'] == 'ready' and st['healthy'] is True


def test_nt_guard_returns_graceful_error(app, monkeypatch):
    monkeypatch.setattr(TramoHostService, '_is_windows', classmethod(lambda cls: True))
    assert TramoHostService.is_installed() is False
    d = TramoHostService._docker(['ps'])
    assert d['success'] is False and 'Windows' in d['error']
    st = TramoHostService.get_status()
    assert st['state'] == 'not_installed'
    inst = TramoHostService.install()
    assert inst['success'] is False and 'Windows' in inst['error']


# --------------------------------------------------------------------------- #
# run_sync
# --------------------------------------------------------------------------- #
def test_upsert_run_inserts_then_updates(app):
    row1, new1 = run_sync_mod.upsert_run({'id': 'r1', 'status': 'running',
                                          'workflowId': 'flow-a'})
    assert new1 is True and row1.status == 'running'
    row2, new2 = run_sync_mod.upsert_run({'id': 'r1', 'status': 'success'})
    assert new2 is False and row2.status == 'success'
    assert TramoRun.query.filter_by(run_id='r1').count() == 1


def test_upsert_run_ignores_missing_id(app):
    row, new = run_sync_mod.upsert_run({'status': 'success'})
    assert row is None and new is False


# --------------------------------------------------------------------------- #
# jobs
# --------------------------------------------------------------------------- #
def test_harvest_upserts_and_notifies_once(app, monkeypatch):
    monkeypatch.setattr(TramoHostService, 'is_installed', classmethod(lambda cls: True))
    runs = [{'id': 'a', 'status': 'success'}, {'id': 'b', 'status': 'failed'}]
    monkeypatch.setattr(TramoHostService, '_api',
                        classmethod(lambda cls, m, p, payload=None, timeout=None: {'success': True, 'data': runs}))
    sent = []
    monkeypatch.setattr('app.plugins_sdk.notify.send',
                        lambda *a, **k: sent.append((a, k)))
    r1 = jobs_mod.harvest_runs(None)
    assert r1['harvested'] == 2 and r1['new_failures'] == 1
    # Second harvest: no new rows, no new failure notifications.
    r2 = jobs_mod.harvest_runs(None)
    assert r2['new_failures'] == 0
    assert len(sent) == 1
    assert TramoRun.query.count() == 2


def test_health_check_notifies_after_threshold(app, monkeypatch):
    _mk_plugin_row()
    monkeypatch.setattr(TramoHostService, 'is_installed', classmethod(lambda cls: True))
    monkeypatch.setattr(TramoHostService, 'health',
                        classmethod(lambda cls: {'success': False, 'error': 'down'}))
    sent = []
    monkeypatch.setattr('app.plugins_sdk.notify.send', lambda *a, **k: sent.append(k))
    jobs_mod.health_check(None)          # streak 1: no notify
    assert len(sent) == 0
    jobs_mod.health_check(None)          # streak 2: notify
    assert len(sent) == 1
    # Recovery resets the streak.
    monkeypatch.setattr(TramoHostService, 'health',
                        classmethod(lambda cls: {'success': True}))
    jobs_mod.health_check(None)
    assert TramoHostService._config().get('health_fail_streak') == 0


# --------------------------------------------------------------------------- #
# events bridge + call-back key
# --------------------------------------------------------------------------- #
def test_events_bridge_toggle(app):
    _mk_plugin_row()
    _mk_admin()
    from app.models.event_subscription import EventSubscription
    sub_id = eb_mod.enable_events_bridge()
    assert sub_id is not None
    sub = EventSubscription.query.get(sub_id)
    assert sub.get_events() == ['*']
    assert '/sk/events' in sub.url
    assert eb_mod.is_events_bridge_enabled() is True
    # Idempotent.
    assert eb_mod.enable_events_bridge() == sub_id
    # Disable removes it.
    assert eb_mod.disable_events_bridge() is True
    assert EventSubscription.query.get(sub_id) is None
    assert eb_mod.is_events_bridge_enabled() is False


def test_callback_key_issue_and_revoke(app):
    _mk_plugin_row()
    _mk_admin()
    from app.models.api_key import ApiKey
    raw = eb_mod.issue_callback_key()
    assert raw and raw.startswith('sk_')
    key_id = eb_mod._config().get('callback_key_id')
    key = ApiKey.query.get(key_id)
    assert key.name == 'serverkit-tramo'
    assert 'apps:deploy' in key.get_scopes()
    assert key.is_valid() is True
    eb_mod.revoke_callback_key()
    from app import db
    db.session.refresh(key)
    assert key.is_active is False and key.revoked_at is not None


def test_uninstall_revokes_key_and_subscription(app, monkeypatch):
    _mk_plugin_row()
    _mk_admin()
    from app.models.api_key import ApiKey
    from app.models.event_subscription import EventSubscription
    eb_mod.issue_callback_key()
    eb_mod.enable_events_bridge()
    key_id = eb_mod._config().get('callback_key_id')
    sub_id = eb_mod._config().get('events_subscription_id')
    # Container teardown is a no-op here (not installed).
    monkeypatch.setattr(TramoHostService, 'is_installed', classmethod(lambda cls: False))
    lifecycle = importlib.import_module(f'app.plugins.{SLUG}.lifecycle')
    lifecycle.on_uninstall(SimpleNamespace(slug=SLUG), purge=False)
    from app import db
    key = ApiKey.query.get(key_id)
    assert key.is_active is False
    assert EventSubscription.query.get(sub_id) is None


# --------------------------------------------------------------------------- #
# blueprint: auth, run proxy, runs filter, settings mask, hooks passthrough
# --------------------------------------------------------------------------- #
def test_routes_require_auth(tramo_client):
    assert tramo_client.get('/api/v1/tramo/workflows').status_code in (401, 422)
    assert tramo_client.get('/api/v1/tramo/host/status').status_code in (401, 422)


def test_workflow_crud_via_routes(tramo_client, auth_headers):
    r = tramo_client.post('/api/v1/tramo/workflows', headers=auth_headers,
                          json={'name': 'Route Flow'})
    assert r.status_code == 201
    slug = r.get_json()['slug']
    assert tramo_client.get(f'/api/v1/tramo/workflows/{slug}',
                            headers=auth_headers).status_code == 200
    lst = tramo_client.get('/api/v1/tramo/workflows', headers=auth_headers).get_json()
    assert any(w['slug'] == slug for w in lst['workflows'])


def test_run_proxy_persists_row(tramo_client, auth_headers, monkeypatch):
    WorkflowStore.create('runme')
    monkeypatch.setattr(bp_mod.TramoHostService, 'is_installed', classmethod(lambda cls: True))
    monkeypatch.setattr(bp_mod.TramoHostService, '_api',
                        classmethod(lambda cls, m, p, payload=None, timeout=None:
                                    {'success': True, 'data': {'id': 'run-77', 'status': 'success',
                                                               'workflowId': 'runme'}}))
    r = tramo_client.post('/api/v1/tramo/workflows/runme/run', headers=auth_headers, json={})
    assert r.status_code == 200
    assert r.get_json()['run']['run_id'] == 'run-77'
    assert TramoRun.query.filter_by(run_id='run-77').count() == 1


def test_runs_list_filters_by_workflow(tramo_client, auth_headers, app):
    run_sync_mod.upsert_run({'id': 'x1', 'status': 'success', 'workflowId': 'flowA'})
    run_sync_mod.upsert_run({'id': 'x2', 'status': 'success', 'workflowId': 'flowB'})
    r = tramo_client.get('/api/v1/tramo/runs?workflow=flowA', headers=auth_headers)
    runs = r.get_json()['runs']
    assert len(runs) == 1 and runs[0]['run_id'] == 'x1'


def test_settings_masks_secret_values(tramo_client, auth_headers, app):
    _mk_plugin_row()
    tramo_client.put('/api/v1/tramo/settings', headers=auth_headers,
                     json={'pack_secrets': {'TELEGRAM_BOT_TOKEN': 'shh'}})
    body = tramo_client.get('/api/v1/tramo/settings', headers=auth_headers).get_json()
    assert 'TELEGRAM_BOT_TOKEN' in body['pack_secret_names']
    # The value must never be echoed anywhere in the settings response.
    assert 'shh' not in json.dumps(body)


def test_hooks_passthrough_is_auth_exempt_and_forwards(tramo_client, monkeypatch):
    monkeypatch.setattr(bp_mod.TramoHostService, 'is_installed', classmethod(lambda cls: True))
    monkeypatch.setattr(bp_mod.TramoHostService, 'host_port', classmethod(lambda cls: 8377))
    captured = {}

    def fake_request(method, url, **kw):
        captured['method'] = method
        captured['url'] = url
        captured['data'] = kw.get('data')
        return SimpleNamespace(status_code=200, content=b'{"ok":true}',
                               headers={'Content-Type': 'application/json'})

    monkeypatch.setattr(bp_mod.requests, 'request', fake_request)
    # NO auth headers -> still reachable (auth-exempt).
    r = tramo_client.post('/api/v1/tramo/hooks/my-trigger', data=b'{"a":1}',
                          content_type='application/json')
    assert r.status_code == 200
    assert captured['method'] == 'POST'
    assert captured['url'].endswith('/hooks/my-trigger')
    assert captured['data'] == b'{"a":1}'


def test_starter_templates_route(tramo_client, auth_headers):
    r = tramo_client.get('/api/v1/tramo/templates', headers=auth_headers)
    ids = [t['id'] for t in r.get_json()['templates']]
    assert 'backup-failed-telegram' in ids
    # Instantiate one.
    c = tramo_client.post('/api/v1/tramo/workflows/from-template/backup-failed-telegram',
                          headers=auth_headers, json={})
    assert c.status_code == 201
    assert c.get_json()['doc']['nodes']


# --------------------------------------------------------------------------- #
# Phase 4: retired engine + ported emitters + legacy export
# --------------------------------------------------------------------------- #
def test_legacy_workflows_route_admin_only(tramo_client, auth_headers, app):
    # Admin gets a (possibly empty) list, never a 500.
    r = tramo_client.get('/api/v1/tramo/legacy-workflows', headers=auth_headers)
    assert r.status_code == 200
    assert 'workflows' in r.get_json()


def test_old_workflows_routes_are_gone(client, auth_headers):
    # The /api/v1/workflows blueprint was removed in Phase 4.
    r = client.get('/api/v1/workflows', headers=auth_headers)
    assert r.status_code == 404
    # The execute route no longer has a POST handler; the SPA catch-all is
    # GET-only, so an unmatched POST is 404/405 -- either proves it is gone.
    r2 = client.post('/api/v1/workflows/1/execute', headers=auth_headers, json={})
    assert r2.status_code in (404, 405)


def test_event_catalog_has_ported_types():
    from app.services.event_service import EVENT_CATALOG
    types = {e['type'] for e in EVENT_CATALOG}
    assert {'health.check_failed', 'git.push',
            'monitor.high_cpu', 'monitor.high_memory'} <= types


def _wildcard_sub(app):
    from app import db
    from app.models.event_subscription import EventSubscription
    admin = _mk_admin()
    sub = EventSubscription(user_id=admin.id, name='cap', url='http://x/y', is_active=True)
    sub.set_events(['*'])
    db.session.add(sub)
    db.session.commit()
    return sub


def test_ported_emitters_reach_event_service(app, monkeypatch):
    from app.services.event_service import EventService
    from app.models.event_subscription import EventDelivery
    _wildcard_sub(app)
    enqueued = []
    monkeypatch.setattr('app.services.event_service.enqueue_webhook_delivery',
                        lambda did: enqueued.append(did))
    for evt in ('health.check_failed', 'git.push', 'monitor.high_cpu'):
        EventService.emit(evt, {'event': evt})
    delivered = {d.event_type for d in EventDelivery.query.all()}
    assert {'health.check_failed', 'git.push', 'monitor.high_cpu'} <= delivered
    assert len(enqueued) == 3


def test_app_stopped_not_double_emitted_by_docker_service(app, monkeypatch):
    """docker_service.stop_container no longer emits app.stopped itself."""
    from app.models.event_subscription import EventDelivery
    _wildcard_sub(app)
    from app.services.docker_service import DockerService
    monkeypatch.setattr('app.services.event_service.enqueue_webhook_delivery',
                        lambda did: None)
    monkeypatch.setattr(
        'app.services.docker_service.subprocess.run',
        lambda *a, **k: SimpleNamespace(returncode=0, stdout='', stderr=''))
    res = DockerService.stop_container('abc123')
    assert res['success'] is True
    # No app.stopped delivery came from the low-level stop helper.
    assert EventDelivery.query.filter_by(event_type='app.stopped').count() == 0
