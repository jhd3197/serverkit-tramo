"""Run persistence helpers (serverkit-tramo / Automations extension).

``@tramo/server`` keeps run history in an in-memory ring of 1000 (it evicts old
runs and loses everything on restart), so the panel harvests run summaries into
:class:`TramoRun`. Both the harvest job and the manual-run proxy funnel through
:func:`upsert_run` (keyed on the tramo run id) so a run is never duplicated.

tramo's run JSON field names are not frozen, so :func:`parse_run` reads a few
aliases defensively and keeps the untouched original in ``raw``.
"""
import json
import logging
from datetime import datetime

from app import db

from .models import TramoRun

logger = logging.getLogger(__name__)


def _first(d, *keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ''):
            return d.get(k)
    return None


def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.utcfromtimestamp(value / 1000 if value > 1e12 else value)
        except (ValueError, OSError):
            return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _json_dump(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return None


def parse_run(run_json):
    """Map a tramo run object to TramoRun column values (dict)."""
    run_id = _first(run_json, 'id', 'runId', 'run_id')
    return {
        'run_id': str(run_id) if run_id is not None else None,
        'workflow_slug': _first(run_json, 'workflowId', 'workflow_id',
                                'workflowSlug', 'workflow_slug', 'workflow'),
        'status': _first(run_json, 'status', 'state'),
        'source': _first(run_json, 'source', 'trigger', 'triggerType', 'trigger_type'),
        'error': _first(run_json, 'error', 'errorMessage', 'error_message'),
        'usage': _json_dump(_first(run_json, 'usage', 'cost', 'tokens')),
        'pending_approvals': _json_dump(_first(run_json, 'pendingApprovals',
                                               'pending_approvals', 'approvals')),
        'started_at': _parse_dt(_first(run_json, 'startedAt', 'started_at', 'startTime')),
        'finished_at': _parse_dt(_first(run_json, 'finishedAt', 'finished_at',
                                        'endTime', 'completedAt')),
        'raw': _json_dump(run_json),
    }


def upsert_run(run_json):
    """Insert or update a TramoRun from a tramo run object.

    Returns ``(row, is_new)``. ``is_new`` is True only when the row did not exist
    before, so callers can fire a one-shot notification on first sight.
    """
    fields = parse_run(run_json)
    if not fields.get('run_id'):
        return None, False

    row = TramoRun.query.filter_by(run_id=fields['run_id']).first()
    is_new = row is None
    if is_new:
        row = TramoRun(run_id=fields['run_id'])
        db.session.add(row)
    for key, value in fields.items():
        if key == 'run_id':
            continue
        setattr(row, key, value)
    db.session.commit()
    return row, is_new
