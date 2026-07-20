"""Automations API endpoints (serverkit-tramo extension, tramo engine).

Mounted under ``/api/v1/tramo`` via the manifest's ``url_prefix``. Thin routing
layer over the extension services -- all Docker, tramo-API, and DB work happens
in :mod:`host_service`, :mod:`workflow_store`, :mod:`run_sync`, and
:mod:`events_bridge`.

Auth split (same as serverkit-mail / serverkit-k8s): reads need viewer, mutations
need admin. The ONE exception is the inbound-webhook passthrough
(``/hooks/<path>``) which is intentionally auth-exempt so external services can
POST to a workflow's ``webhook-trigger`` node through the panel's public domain;
per-trigger HMAC (tramo native) covers spoofing and the container stays
loopback-only. The plugin-disabled 503 guard (attached by plugin_service) still
runs on every route including the passthrough.
"""
import logging

import requests
from flask import Blueprint, jsonify, request, Response

from app.middleware.rbac import admin_required, viewer_required

from .host_service import TramoHostService, RUN_TIMEOUT
from .workflow_store import WorkflowStore
from . import events_bridge
from .run_sync import upsert_run
from .models import TramoRun

logger = logging.getLogger(__name__)

tramo_bp = Blueprint('tramo', __name__)

_NOT_INSTALLED = ('The Automations engine is not installed. Install it from the '
                  'Automations Settings tab (admin only).')

# Response/hop headers we must not blindly relay when proxying.
_HOP_HEADERS = {'content-length', 'transfer-encoding', 'connection',
                'content-encoding', 'host'}


def _installed_or_error():
    if not TramoHostService.is_installed():
        return jsonify({'error': _NOT_INSTALLED}), 503
    return None


# ── Workflows CRUD ──

@tramo_bp.route('/workflows', methods=['GET'])
@viewer_required
def list_workflows():
    return jsonify({'workflows': WorkflowStore.list_workflows()}), 200


@tramo_bp.route('/workflows/<slug>', methods=['GET'])
@viewer_required
def get_workflow(slug):
    wf = WorkflowStore.get(slug)
    if not wf:
        return jsonify({'error': 'Workflow not found'}), 404
    return jsonify(wf.to_dict(include_doc=True)), 200


@tramo_bp.route('/workflows', methods=['POST'])
@admin_required
def create_workflow():
    data = request.get_json(silent=True) or {}
    try:
        wf = WorkflowStore.create(
            name=data.get('name'),
            doc=data.get('doc'),
            enabled=data.get('enabled', True),
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(wf.to_dict(include_doc=True)), 201


@tramo_bp.route('/workflows/<slug>', methods=['PUT'])
@admin_required
def update_workflow(slug):
    data = request.get_json(silent=True) or {}
    try:
        wf = WorkflowStore.update(
            slug,
            name=data.get('name'),
            doc=data.get('doc'),
            enabled=data.get('enabled'),
        )
    except ValueError as e:
        code = 404 if 'not found' in str(e).lower() else 400
        return jsonify({'error': str(e)}), code
    return jsonify(wf.to_dict(include_doc=True)), 200


@tramo_bp.route('/workflows/<slug>', methods=['DELETE'])
@admin_required
def delete_workflow(slug):
    try:
        WorkflowStore.delete(slug)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    return jsonify({'deleted': True}), 200


@tramo_bp.route('/deploy', methods=['POST'])
@admin_required
def deploy():
    result = WorkflowStore.deploy()
    if not result.get('success'):
        code = 503 if 'not installed' in (result.get('error') or '') else 400
        return jsonify({'error': result.get('error', 'Deploy failed'),
                        'materialized': result.get('materialized')}), code
    return jsonify(result), 200


# ── Starter templates ──

@tramo_bp.route('/templates', methods=['GET'])
@viewer_required
def list_starter_templates():
    from .templates import list_templates
    return jsonify({'templates': list_templates()}), 200


@tramo_bp.route('/workflows/from-template/<template_id>', methods=['POST'])
@admin_required
def create_from_template(template_id):
    from .templates import get_template
    tpl = get_template(template_id)
    if not tpl:
        return jsonify({'error': 'Template not found'}), 404
    data = request.get_json(silent=True) or {}
    try:
        wf = WorkflowStore.create(
            name=data.get('name') or tpl['name'],
            doc=tpl['doc'],
            enabled=data.get('enabled', True),
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(wf.to_dict(include_doc=True)), 201


# ── Runs / approvals (proxied to the engine) ──

@tramo_bp.route('/workflows/<slug>/run', methods=['POST'])
@admin_required
def run_workflow(slug):
    guard = _installed_or_error()
    if guard:
        return guard
    wf = WorkflowStore.get(slug)
    if not wf:
        return jsonify({'error': 'Workflow not found'}), 404
    payload = request.get_json(silent=True) or {}
    res = TramoHostService._api('POST', f'/workflows/{slug}/run', payload,
                                timeout=RUN_TIMEOUT)
    if not res.get('success'):
        return jsonify({'error': res.get('error', 'Run failed')}), 502
    summary = res.get('data') or {}
    try:
        row, _ = upsert_run(summary if isinstance(summary, dict) else {})
        run_dict = row.to_dict() if row else None
    except Exception as e:  # noqa: BLE001
        logger.warning('tramo: failed to persist run summary: %s', e)
        run_dict = None
    return jsonify({'run': run_dict, 'result': summary}), 200


@tramo_bp.route('/runs', methods=['GET'])
@viewer_required
def list_runs():
    q = TramoRun.query
    slug = request.args.get('workflow')
    status = request.args.get('status')
    if slug:
        q = q.filter_by(workflow_slug=slug)
    if status:
        q = q.filter_by(status=status)
    try:
        limit = min(int(request.args.get('limit', 100)), 500)
    except (TypeError, ValueError):
        limit = 100
    rows = q.order_by(TramoRun.id.desc()).limit(limit).all()
    return jsonify({'runs': [r.to_dict() for r in rows]}), 200


@tramo_bp.route('/runs/<run_id>', methods=['GET'])
@viewer_required
def get_run(run_id):
    row = TramoRun.query.filter_by(run_id=run_id).first()
    if not row:
        return jsonify({'error': 'Run not found'}), 404
    return jsonify(row.to_dict()), 200


@tramo_bp.route('/runs/<run_id>/replay', methods=['POST'])
@admin_required
def replay_run(run_id):
    guard = _installed_or_error()
    if guard:
        return guard
    res = TramoHostService._api('POST', f'/runs/{run_id}/replay')
    if not res.get('success'):
        return jsonify({'error': res.get('error', 'Replay failed')}), 502
    try:
        if isinstance(res.get('data'), dict):
            upsert_run(res['data'])
    except Exception as e:  # noqa: BLE001
        logger.debug('replay upsert failed: %s', e)
    return jsonify(res.get('data') or {'replayed': True}), 200


@tramo_bp.route('/approvals', methods=['GET'])
@viewer_required
def list_approvals():
    guard = _installed_or_error()
    if guard:
        return guard
    res = TramoHostService._api('GET', '/approvals')
    if not res.get('success'):
        return jsonify({'approvals': [], 'note': res.get('error')}), 200
    data = res.get('data')
    approvals = data if isinstance(data, list) else (data or {}).get('approvals', [])
    return jsonify({'approvals': approvals}), 200


@tramo_bp.route('/runs/<run_id>/approve', methods=['POST'])
@admin_required
def approve_run(run_id):
    guard = _installed_or_error()
    if guard:
        return guard
    payload = request.get_json(silent=True) or {}
    res = TramoHostService._api('POST', f'/runs/{run_id}/approve', payload)
    if not res.get('success'):
        return jsonify({'error': res.get('error', 'Approve failed')}), 502
    return jsonify(res.get('data') or {'approved': True}), 200


# ── Host (engine) lifecycle ──

@tramo_bp.route('/host/status', methods=['GET'])
@viewer_required
def host_status():
    return jsonify(TramoHostService.get_status()), 200


@tramo_bp.route('/host/install', methods=['POST'])
@admin_required
def host_install():
    data = request.get_json(silent=True) or {}
    # Issue the scoped call-back key so workflows can act back on the panel.
    callback_key = events_bridge.issue_callback_key()
    result = TramoHostService.install(
        host_port=data.get('host_port'),
        callback_api_key=callback_key,
    )
    if not result.get('success'):
        # Roll back the key we just issued if the container didn't start.
        events_bridge.revoke_callback_key()
        return jsonify({'error': result.get('error', 'Install failed')}), 400
    return jsonify(result), 201


@tramo_bp.route('/host/install', methods=['DELETE'])
@admin_required
def host_uninstall():
    keep_data = (request.args.get('keep_data', 'true').lower()
                 not in ('false', '0', 'no'))
    result = TramoHostService.uninstall(keep_data=keep_data)
    events_bridge.revoke_callback_key()
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Uninstall failed')}), 400
    return jsonify(result), 200


@tramo_bp.route('/host/control/<action>', methods=['POST'])
@admin_required
def host_control(action):
    guard = _installed_or_error()
    if guard:
        return guard
    result = TramoHostService.control(action)
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Control failed')}), 400
    return jsonify(result), 200


# ── Settings ──

@tramo_bp.route('/settings', methods=['GET'])
@viewer_required
def get_settings():
    return jsonify({
        'host_port': TramoHostService.host_port(),
        'events_bridge_enabled': events_bridge.is_events_bridge_enabled(),
        # Names only -- secret values are never returned.
        'pack_secret_names': sorted(TramoHostService.get_pack_secrets().keys()),
    }), 200


@tramo_bp.route('/settings', methods=['PUT'])
@admin_required
def update_settings():
    data = request.get_json(silent=True) or {}
    out = {}

    if 'pack_secrets' in data and isinstance(data['pack_secrets'], dict):
        out['pack_secret_names'] = TramoHostService.set_pack_secrets(data['pack_secrets'])

    if 'host_port' in data:
        try:
            port = int(data['host_port'])
            if not (1024 <= port <= 65535):
                raise ValueError
            TramoHostService._save_config({'host_port': port})
            out['host_port'] = port
        except (TypeError, ValueError):
            return jsonify({'error': 'host_port must be an integer 1024-65535'}), 400

    if 'events_bridge_enabled' in data:
        if data['events_bridge_enabled']:
            events_bridge.enable_events_bridge()
        else:
            events_bridge.disable_events_bridge()
        out['events_bridge_enabled'] = events_bridge.is_events_bridge_enabled()

    return jsonify(out), 200


# ── Legacy Workflow Builder export (read-only, admin) ──

@tramo_bp.route('/legacy-workflows', methods=['GET'])
@admin_required
def legacy_workflows():
    """Read-only dump of the retired Workflow Builder's rows (plan 45 Phase 4).

    The old ``workflows`` tables are kept (no data loss); this lets an operator
    rebuild those flows by hand in tramo. Never fails if the model is gone.
    """
    try:
        from app.models.workflow import Workflow
    except Exception:  # noqa: BLE001
        return jsonify({'workflows': [], 'note': 'legacy workflow model not present'}), 200
    try:
        rows = Workflow.query.all()
        out = [w.to_dict() if hasattr(w, 'to_dict') else {'id': w.id, 'name': getattr(w, 'name', None)}
               for w in rows]
    except Exception as e:  # noqa: BLE001
        return jsonify({'workflows': [], 'note': f'could not read legacy workflows: {e}'}), 200
    return jsonify({'workflows': out}), 200


# ── Inbound webhook passthrough (AUTH-EXEMPT) ──

@tramo_bp.route('/hooks/<path:subpath>',
                methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
def hooks_passthrough(subpath):
    """Forward an external webhook to the engine's trigger dispatcher.

    Intentionally has NO auth decorator: external services POST here through the
    panel's public domain to fire a ``webhook-trigger`` node. The container is
    loopback-only, so this is the only way in; per-trigger HMAC (configured on
    the node) authenticates the payload.
    """
    if not TramoHostService.is_installed():
        return jsonify({'error': _NOT_INSTALLED}), 503

    target = f'http://127.0.0.1:{TramoHostService.host_port()}/hooks/{subpath}'
    fwd_headers = {k: v for k, v in request.headers
                   if k.lower() not in _HOP_HEADERS}
    try:
        upstream = requests.request(
            request.method, target,
            params=request.args,
            data=request.get_data(),
            headers=fwd_headers,
            timeout=30,
        )
    except requests.RequestException as e:
        return jsonify({'error': f'Automations engine unreachable: {e}'}), 502

    resp_headers = [(k, v) for k, v in upstream.headers.items()
                    if k.lower() not in _HOP_HEADERS]
    return Response(upstream.content, status=upstream.status_code, headers=resp_headers)
