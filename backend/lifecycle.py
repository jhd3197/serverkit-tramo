"""Install / uninstall lifecycle hooks (serverkit-tramo / Automations extension).

Contract (per the plugin SDK): a single positional arg -- the InstalledPlugin
row. ``on_uninstall`` also accepts a ``purge`` flag. Everything here is wrapped
so a hook failure never blocks install/uninstall.

``on_install`` registers the extension's notification events and retires any
ghost ``serverkit-workflows`` row left over from the builder this extension
replaces (plan 45 Phase 4). It does NOT start the container -- the operator does
that from the Automations Settings tab (mail pattern).

``on_uninstall`` tears down everything provisioned by the engine: the container,
the scoped call-back ApiKey, and the managed events-bridge subscription. Data
dirs are deleted only on ``--purge``.
"""
import logging

logger = logging.getLogger(__name__)


def on_install(plugin):
    """Register notification events; retire the replaced Workflow Builder row."""
    try:
        from app.plugins_sdk import notify
        notify.register_event(
            'tramo.host_unreachable',
            'The Automations engine became unreachable',
            template='generic', severity='warning', category='system')
        notify.register_event(
            'tramo.run_failed',
            'An automation run failed',
            template='generic', severity='warning', category='system')
        logger.info('serverkit-tramo installed: notification events registered')
    except Exception as e:  # noqa: BLE001
        logger.warning('serverkit-tramo on_install notify hook error: %s', e)

    _retire_workflow_builder_row()


def _retire_workflow_builder_row():
    """Remove any lingering serverkit-workflows InstalledPlugin row.

    The Workflow Builder extension is deleted from disk in plan 45 Phase 4, so
    its backend/frontend no longer load, but an old InstalledPlugin row would
    otherwise haunt the Marketplace as a broken entry (uninstall deletes the
    row, so we mirror that). Best-effort.
    """
    try:
        from app import db
        from app.models.plugin import InstalledPlugin
        row = InstalledPlugin.query.filter_by(slug='serverkit-workflows').first()
        if row:
            db.session.delete(row)
            db.session.commit()
            logger.info('serverkit-tramo: retired ghost serverkit-workflows row')
    except Exception as e:  # noqa: BLE001
        logger.debug('serverkit-tramo: could not retire workflows row: %s', e)


def on_uninstall(plugin, purge=False):
    """Stop/remove the container, revoke the call-back key, drop the events sub."""
    try:
        from .host_service import TramoHostService
        if TramoHostService.is_installed():
            result = TramoHostService.uninstall(keep_data=not purge)
            logger.info('serverkit-tramo on_uninstall container: %s', result)
        else:
            logger.info('serverkit-tramo on_uninstall: container not present')
    except Exception as e:  # noqa: BLE001
        logger.warning('serverkit-tramo on_uninstall container error: %s', e)

    try:
        from . import events_bridge
        events_bridge.revoke_callback_key()
        events_bridge.disable_events_bridge()
        logger.info('serverkit-tramo on_uninstall: call-back key + events bridge removed')
    except Exception as e:  # noqa: BLE001
        logger.warning('serverkit-tramo on_uninstall bridge error: %s', e)
