"""Background job handlers (serverkit-tramo / Automations extension).

Registered via the manifest ``jobs`` block; each handler takes the ``job`` row
and must never raise (a raised handler fails the job loudly -- these are
best-effort maintenance tasks).

* ``tramo.harvest_runs`` (:func:`harvest_runs`) -- pull recent runs from the
  engine and upsert them into ``ext_serverkit_tramo_runs`` before the container's
  in-memory ring evicts them; notify admins once per newly-seen failed run.
* ``tramo.health_check`` (:func:`health_check`) -- probe ``GET /api/health`` and
  notify ``tramo.host_unreachable`` after repeated failures.
"""
import logging

logger = logging.getLogger(__name__)

SLUG = 'serverkit-tramo'

# Consecutive health failures before we notify (avoids flapping on a restart).
_HEALTH_FAIL_THRESHOLD = 2


def harvest_runs(job):
    """Harvest recent runs from the engine into the DB. Never raises."""
    try:
        from .host_service import TramoHostService
        from .run_sync import upsert_run

        if not TramoHostService.is_installed():
            return {'skipped': True, 'reason': 'engine not installed'}

        res = TramoHostService._api('GET', '/runs?limit=200')
        if not res.get('success'):
            return {'skipped': True, 'reason': res.get('error', 'runs fetch failed')}

        data = res.get('data')
        runs = data if isinstance(data, list) else (data or {}).get('runs') \
            or (data or {}).get('items') or []

        harvested = 0
        new_failures = 0
        for run_json in runs:
            row, is_new = upsert_run(run_json)
            if row is None:
                continue
            harvested += 1
            if is_new and (row.status or '').lower() in ('failed', 'error'):
                _notify_run_failed(row)
                new_failures += 1

        return {'harvested': harvested, 'new_failures': new_failures}
    except Exception as e:  # noqa: BLE001 -- a maintenance job must not crash the loop
        logger.warning('tramo harvest_runs job failed: %s', e)
        return {'error': str(e)}


def _notify_run_failed(row):
    try:
        from app.plugins_sdk import notify
        notify.send('tramo.run_failed', to='admins',
                    data={'run_id': row.run_id,
                          'workflow': row.workflow_slug,
                          'error': row.error},
                    category='system')
    except Exception as e:  # noqa: BLE001
        logger.debug('tramo.run_failed notify failed: %s', e)


def health_check(job):
    """Probe engine health; notify after repeated failure. Never raises."""
    try:
        from .host_service import TramoHostService

        if not TramoHostService.is_installed():
            _reset_health_streak()
            return {'skipped': True, 'reason': 'engine not installed'}

        res = TramoHostService.health()
        if res.get('success'):
            _reset_health_streak()
            return {'healthy': True}

        streak = _bump_health_streak()
        if streak == _HEALTH_FAIL_THRESHOLD:
            _notify_unreachable(res.get('error'))
        return {'healthy': False, 'streak': streak}
    except Exception as e:  # noqa: BLE001
        logger.warning('tramo health_check job failed: %s', e)
        return {'error': str(e)}


def _health_config():
    from app.plugins_sdk import config as plugin_config
    return plugin_config(SLUG)


def _save_health(updates):
    from app import db
    from app.models.plugin import InstalledPlugin
    row = InstalledPlugin.query.filter_by(slug=SLUG).first()
    if not row:
        return
    merged = dict(row.config or {})
    merged.update(updates)
    row.config = merged
    db.session.commit()


def _bump_health_streak():
    streak = int(_health_config().get('health_fail_streak') or 0) + 1
    _save_health({'health_fail_streak': streak})
    return streak


def _reset_health_streak():
    if _health_config().get('health_fail_streak'):
        _save_health({'health_fail_streak': 0})


def _notify_unreachable(error):
    try:
        from app.plugins_sdk import notify
        notify.send('tramo.host_unreachable', to='admins',
                    data={'error': error}, category='system')
    except Exception as e:  # noqa: BLE001
        logger.debug('tramo.host_unreachable notify failed: %s', e)
