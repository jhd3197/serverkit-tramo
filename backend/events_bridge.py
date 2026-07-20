"""Panel <-> tramo wiring (serverkit-tramo / Automations extension, plan 45 Phase 3).

Two integrations that let panel automations reach the outside world and act back
on the panel:

* **Events bridge** — one managed :class:`EventSubscription` whose ``url`` points
  at the container's ``serverkit:event`` webhook trigger (``/sk/events`` via the
  hooks passthrough). Subscribing to ``["*"]`` means every panel event is POSTed
  to tramo; workflows filter with ``if``/``switch`` on ``trigger.body.event``.
  Toggled on/off from the Settings tab; its id is remembered in plugin config.

* **Call-back key** — a scoped :class:`ApiKey` named ``serverkit-tramo`` issued
  on engine install and injected into the container as ``SERVERKIT_API_KEY`` so
  the ``@tramo/serverkit`` pack can start/stop/deploy apps, run backups, and send
  notifications. Revoked on uninstall.

All helpers are best-effort and never raise into install/uninstall.
"""
import logging

from app import db

logger = logging.getLogger(__name__)

SLUG = 'serverkit-tramo'

# Scopes the call-back key is granted. Matches the @tramo/serverkit pack actions:
# app-control/deploy (apps:*), backup-run (backups:write), list/get (read).
CALLBACK_KEY_NAME = 'serverkit-tramo'
CALLBACK_SCOPES = ['read', 'apps:read', 'apps:write', 'apps:deploy', 'backups:write']

# The path (under the hooks passthrough) the managed subscription targets, and
# which the container maps to a serverkit:event webhook-trigger node.
EVENTS_TRIGGER_PATH = 'sk/events'


def _config():
    from app.plugins_sdk import config as plugin_config
    return plugin_config(SLUG)


def _save_config(updates):
    from app.models.plugin import InstalledPlugin
    row = InstalledPlugin.query.filter_by(slug=SLUG).first()
    if not row:
        return False
    merged = dict(row.config or {})
    merged.update(updates)
    row.config = merged
    db.session.commit()
    return True


def _admin_user_id():
    """Owner for the managed ApiKey / EventSubscription (first admin, else any)."""
    from app.models.user import User
    admin = User.query.filter_by(role=User.ROLE_ADMIN).order_by(User.id).first()
    if admin:
        return admin.id
    any_user = User.query.order_by(User.id).first()
    return any_user.id if any_user else None


# --------------------------------------------------------------------------- #
# Call-back key
# --------------------------------------------------------------------------- #

def issue_callback_key():
    """Issue (or reissue) the scoped ``serverkit-tramo`` ApiKey.

    Returns the RAW key string (only available at creation) or None on failure.
    The key id is stored in plugin config for later revocation.
    """
    from app.models.api_key import ApiKey

    user_id = _admin_user_id()
    if not user_id:
        logger.warning('tramo: no user to own the call-back API key')
        return None

    # Revoke any previous managed key first (rotate).
    revoke_callback_key()

    raw, prefix, key_hash = ApiKey.generate_key()
    key = ApiKey(
        user_id=user_id,
        name=CALLBACK_KEY_NAME,
        key_prefix=prefix,
        key_hash=key_hash,
    )
    key.set_scopes(CALLBACK_SCOPES)
    db.session.add(key)
    db.session.commit()
    _save_config({'callback_key_id': key.id})
    return raw


def revoke_callback_key():
    """Revoke the managed call-back ApiKey (best-effort)."""
    from datetime import datetime
    from app.models.api_key import ApiKey

    key_id = _config().get('callback_key_id')
    if not key_id:
        return False
    key = ApiKey.query.get(key_id)
    if key:
        key.is_active = False
        key.revoked_at = datetime.utcnow()
        db.session.commit()
    _save_config({'callback_key_id': None})
    return True


# --------------------------------------------------------------------------- #
# Events bridge
# --------------------------------------------------------------------------- #

def is_events_bridge_enabled():
    return bool(_config().get('events_subscription_id'))


def enable_events_bridge():
    """Create the managed EventSubscription (idempotent). Returns its id or None."""
    from app.models.event_subscription import EventSubscription

    existing_id = _config().get('events_subscription_id')
    if existing_id and EventSubscription.query.get(existing_id):
        return existing_id

    user_id = _admin_user_id()
    if not user_id:
        logger.warning('tramo: no user to own the events subscription')
        return None

    from .host_service import TramoHostService
    port = TramoHostService.host_port()
    secret = EventSubscription.generate_secret()

    sub = EventSubscription(
        user_id=user_id,
        name='Automations (tramo) events bridge',
        url=f'http://127.0.0.1:{port}/{EVENTS_TRIGGER_PATH}',
        secret=secret,
        is_active=True,
    )
    sub.set_events(['*'])
    db.session.add(sub)
    db.session.commit()
    _save_config({'events_subscription_id': sub.id, 'events_secret': secret})
    return sub.id


def disable_events_bridge():
    """Delete the managed EventSubscription (best-effort). Returns True if removed."""
    from app.models.event_subscription import EventSubscription

    sub_id = _config().get('events_subscription_id')
    if not sub_id:
        return False
    sub = EventSubscription.query.get(sub_id)
    if sub:
        db.session.delete(sub)
        db.session.commit()
    _save_config({'events_subscription_id': None, 'events_secret': None})
    return True
