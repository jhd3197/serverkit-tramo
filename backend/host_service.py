"""tramo engine host service (serverkit-tramo / Automations extension).

Runs ``@tramo/server`` (the headless tramo workflow host) in a managed Docker
container so the panel host can execute automation workflows: webhooks, cron,
run history, approvals. Driven through tramo's HTTP API, published on loopback
only.

Design mirrors serverkit-mail's :class:`StalwartService` exactly:

* **Two choke-points** — every Docker invocation goes through :meth:`_docker`
  (privilege escalation, timeouts, error shaping) and every tramo-API call goes
  through :meth:`_api` (Bearer auth, JSON, error shaping). Nothing else shells
  out or talks HTTP.
* **Best-effort, Linux-only** — on Windows (dev) or when Docker is absent, calls
  return a clean error dict instead of raising.
* **Panel DB is the source of truth** — workflow docs live in
  ``ext_serverkit_tramo_*``; :mod:`workflow_store` materializes enabled docs into
  the bind-mounted workflows dir and this service restarts the container.
* **Secrets in the config store** — the generated Bearer API key, the container
  ``host_port``, an encrypted map of pack credentials (TELEGRAM_BOT_TOKEN, ...),
  and the scoped panel call-back key all live in the plugin config store
  (``plugins_sdk.config`` + the ``_save_config`` pattern), encrypted at rest.

The container is a *stateless executor*: it reads workflow ``.json`` files once
at boot (no server-side editing) and keeps run history in an in-memory ring, so
the panel harvests runs (see jobs) and re-deploys by restarting the container.
"""
import logging
import os
import secrets
import subprocess

import requests

from app.utils.system import run_privileged, is_command_available

try:
    from app.utils.crypto import encrypt_secret, decrypt_secret_safe
except Exception:  # pragma: no cover - crypto util should always be present
    encrypt_secret = None
    decrypt_secret_safe = None

logger = logging.getLogger(__name__)

SLUG = 'serverkit-tramo'

# Pinned tramo-server image (GHCR, full-pack entry). Bumped deliberately like the
# Stalwart image, not floated. Published by the tramo repo's docker CI (plan 45
# Phase 0); until that ships this tag will not pull on a real box.
IMAGE = 'ghcr.io/jhd3197/tramo-server:0.1.1'
CONTAINER_NAME = 'serverkit-tramo'

# Host data dirs (bind-mounted). workflows/ holds the materialized <slug>.json
# docs; state/ is tramo's durable checkpoint store (suspend/resume survives a
# restart, so re-deploy = restart is safe).
DATA_DIR = '/var/serverkit/tramo'
HOST_WORKFLOWS_DIR = f'{DATA_DIR}/workflows'
HOST_STATE_DIR = f'{DATA_DIR}/state'
CONTAINER_WORKFLOWS_DIR = '/workflows'
CONTAINER_STATE_DIR = '/state'
CONTAINER_PORT = 3000

# tramo HTTP API — published on 127.0.0.1 only, never reachable off-host.
API_HOST = '127.0.0.1'
DEFAULT_HOST_PORT = 8377
API_TIMEOUT = 15
RUN_TIMEOUT = 120
DOCKER_TIMEOUT = 180

DOCS_URL = 'https://github.com/jhd3197/tramo'


class TramoHostService:
    """Stateless wrapper around Docker + the tramo-server HTTP API."""

    # ---------- config (plugin config store) ----------

    @classmethod
    def _config(cls):
        """Saved extension settings from the plugin config store."""
        from app.plugins_sdk import config as plugin_config
        return plugin_config(SLUG)

    @classmethod
    def _save_config(cls, updates):
        """Merge *updates* into the plugin's stored config.

        The SDK ``config()`` helper is read-only (the panel owns writes), so
        generated secrets are persisted through the InstalledPlugin row directly.
        Returns False when the plugin row is absent (dev shells / tests without a
        row).
        """
        from app import db
        from app.models.plugin import InstalledPlugin
        row = InstalledPlugin.query.filter_by(slug=SLUG).first()
        if not row:
            logger.warning('%s: no InstalledPlugin row; config not persisted', SLUG)
            return False
        merged = dict(row.config or {})
        merged.update(updates)
        row.config = merged
        db.session.commit()
        return True

    # ---------- secret helpers ----------

    @classmethod
    def _encrypt(cls, plaintext):
        if not plaintext:
            return plaintext
        if encrypt_secret is None:
            return plaintext
        return encrypt_secret(plaintext)

    @classmethod
    def _decrypt(cls, value):
        if not value:
            return value
        if decrypt_secret_safe is None:
            return value
        return decrypt_secret_safe(value)

    @classmethod
    def _is_windows(cls):
        """Windows (dev) has no Docker engine for us. Single testable seam so
        tests can force either platform without touching the global ``os.name``
        (which would break ``pathlib``)."""
        return os.name == 'nt'

    @classmethod
    def host_port(cls):
        """Loopback host port the container's API is published on."""
        try:
            return int(cls._config().get('host_port') or DEFAULT_HOST_PORT)
        except (TypeError, ValueError):
            return DEFAULT_HOST_PORT

    @classmethod
    def api_base(cls):
        return f'http://{API_HOST}:{cls.host_port()}/api'

    @classmethod
    def api_key(cls):
        """Decrypted Bearer API key (empty string when not installed)."""
        return cls._decrypt(cls._config().get('api_key')) or ''

    @classmethod
    def get_pack_secrets(cls):
        """Decrypted {ENV_NAME: value} map of pack credentials."""
        stored = cls._config().get('pack_secrets') or {}
        out = {}
        for k, v in stored.items():
            out[k] = cls._decrypt(v)
        return out

    @classmethod
    def set_pack_secrets(cls, secrets_map):
        """Encrypt and persist a {ENV_NAME: value} map. Empty value deletes a key.

        Returns the new set of configured env-var names (values never returned).
        """
        current = dict(cls._config().get('pack_secrets') or {})
        for name, value in (secrets_map or {}).items():
            name = (name or '').strip()
            if not name:
                continue
            if value in (None, ''):
                current.pop(name, None)
            else:
                current[name] = cls._encrypt(str(value))
        cls._save_config({'pack_secrets': current})
        return sorted(current.keys())

    # ---------- docker choke-point ----------

    @classmethod
    def _docker(cls, args, timeout=DOCKER_TIMEOUT):
        """Run ``docker <args>`` and return a normalized result dict. Never raises."""
        if cls._is_windows():
            return {'success': False,
                    'error': 'The Automations extension is not supported on Windows.'}
        if not is_command_available('docker'):
            return {'success': False, 'not_installed': True,
                    'error': 'Docker is not installed on this host.'}
        cmd = ['docker'] + list(args)
        try:
            result = run_privileged(cmd, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': f'docker timed out after {timeout}s'}
        except (OSError, subprocess.SubprocessError) as e:
            return {'success': False, 'error': f'Failed to run docker: {e}'}
        out = {
            'success': result.returncode == 0,
            'returncode': result.returncode,
            'stdout': result.stdout or '',
            'stderr': result.stderr or '',
        }
        if not out['success']:
            out['error'] = (out['stderr'] or out['stdout'] or 'docker failed').strip()
        return out

    # ---------- tramo API choke-point ----------

    @classmethod
    def _api(cls, method, path, payload=None, timeout=API_TIMEOUT):
        """Call the container's tramo HTTP API (loopback only).

        Returns ``{'success': True, 'data': <json-or-None>, 'status_code': int}``
        or an error dict. Auth is Bearer with the generated API key. Never raises.
        """
        if cls._is_windows():
            return {'success': False,
                    'error': 'The Automations extension is not supported on Windows.'}
        key = cls.api_key()
        if not key:
            return {'success': False,
                    'error': 'tramo API key is not configured. Reinstall the engine.'}
        headers = {'Authorization': f'Bearer {key}'}
        try:
            resp = requests.request(
                method, cls.api_base() + path,
                headers=headers, json=payload, timeout=timeout,
            )
        except requests.RequestException as e:
            return {'success': False,
                    'error': f'tramo API is unreachable: {e}'}
        result = {'success': resp.status_code < 400, 'status_code': resp.status_code}
        if resp.status_code >= 400:
            try:
                body = resp.json()
                detail = (body.get('error') or body.get('message')
                          or body.get('detail') or resp.text)
            except ValueError:
                detail = resp.text
            result['error'] = f'tramo API error ({resp.status_code}): {detail}'.strip()
            return result
        if not resp.content:
            result['data'] = None
            return result
        try:
            result['data'] = resp.json()
        except ValueError:
            result['data'] = resp.text
        return result

    # ---------- container lifecycle ----------

    @classmethod
    def is_installed(cls):
        """True when the managed container exists (running or not)."""
        if cls._is_windows():
            return False
        res = cls._docker(['inspect', '--format', '{{.State.Running}}',
                           CONTAINER_NAME], timeout=20)
        return bool(res.get('success'))

    @classmethod
    def _panel_port(cls):
        """Port the panel API listens on (for the container's call-back URL)."""
        return str(cls._config().get('panel_port')
                   or os.environ.get('PORT') or '5000')

    @classmethod
    def get_status(cls):
        """Installed / running / health summary, best-effort."""
        status = {
            'installed': False,
            'running': False,
            'healthy': None,
            'state': 'not_installed',   # not_installed|stopped|unhealthy|ready
            'engine': 'tramo',
            'image': IMAGE,
            'container': CONTAINER_NAME,
            'host_port': cls.host_port(),
            'api': f'{API_HOST}:{cls.host_port()}',
            'docs_url': DOCS_URL,
        }
        if cls._is_windows():
            status['error'] = 'The Automations extension is not supported on Windows.'
            return status
        res = cls._docker(['inspect', '--format', '{{.State.Running}}',
                           CONTAINER_NAME], timeout=20)
        if not res.get('success'):
            return status
        status['installed'] = True
        running = res.get('stdout', '').strip() == 'true'
        status['running'] = running
        if not running:
            status['state'] = 'stopped'
            return status
        # Running: probe health to distinguish ready from starting/unhealthy.
        probe = cls._api('GET', '/health', timeout=8)
        if probe.get('success'):
            status['healthy'] = True
            status['state'] = 'ready'
            data = probe.get('data')
            if isinstance(data, dict):
                status['version'] = data.get('version')
        else:
            status['healthy'] = False
            status['state'] = 'unhealthy'
            status['health_error'] = probe.get('error')
        return status

    @classmethod
    def health(cls):
        """Raw health probe (GET /api/health). Best-effort dict."""
        if not cls.is_installed():
            return {'success': False, 'error': 'The Automations engine is not installed.'}
        return cls._api('GET', '/health', timeout=8)

    @classmethod
    def install(cls, host_port=None, callback_url=None, callback_api_key=None):
        """Create and start the tramo-server container.

        * Workflows + checkpoint state bind-mounted under ``DATA_DIR``.
        * HTTP API published on **127.0.0.1 only** with a generated Bearer key.
        * Pack credentials + the scoped panel call-back key (SERVERKIT_URL /
          SERVERKIT_API_KEY) injected as container env.
        """
        if cls._is_windows():
            return {'success': False,
                    'error': 'The Automations extension is not supported on Windows.'}
        if cls.is_installed():
            return {'success': False,
                    'error': 'The Automations container already exists. Uninstall it first.'}

        port = int(host_port or cls.host_port())

        dir_res = run_privileged(['mkdir', '-p', HOST_WORKFLOWS_DIR, HOST_STATE_DIR])
        if getattr(dir_res, 'returncode', 1) != 0:
            return {'success': False,
                    'error': f'Could not create data directory {DATA_DIR}: '
                             f'{(getattr(dir_res, "stderr", "") or "").strip()}'}

        api_key = secrets.token_urlsafe(32)

        run_args = cls._build_run_args(port, api_key, callback_url, callback_api_key)
        res = cls._docker(run_args)
        if not res.get('success'):
            return {'success': False,
                    'error': res.get('error', 'Failed to start the tramo container')}

        persisted = cls._save_config({
            'api_key': cls._encrypt(api_key),
            'host_port': port,
            'panel_port': cls._panel_port(),
        })
        result = {'success': True,
                  'message': 'Automations engine installed',
                  'container': CONTAINER_NAME,
                  'host_port': port,
                  'state': 'ready'}
        if not persisted:
            result['warning'] = ('Container started but the API key could not be '
                                 'persisted to the plugin config store.')
        return result

    @classmethod
    def _build_run_args(cls, port, api_key, callback_url=None, callback_api_key=None):
        """Assemble the ``docker run`` argv. Split out so tests can assert it."""
        run_args = [
            'run', '-d',
            '--name', CONTAINER_NAME,
            '--restart', 'unless-stopped',
            # Let workflows call back to the panel on the host loopback.
            '--add-host', 'host.docker.internal:host-gateway',
        ]
        # API published on 127.0.0.1 only.
        run_args += ['-p', f'{API_HOST}:{port}:{CONTAINER_PORT}']
        run_args += [
            '-v', f'{HOST_WORKFLOWS_DIR}:{CONTAINER_WORKFLOWS_DIR}',
            '-v', f'{HOST_STATE_DIR}:{CONTAINER_STATE_DIR}',
        ]
        # Bearer auth + load all first-party integration packs (full-pack entry).
        run_args += ['-e', f'TRAMO_API_KEY={api_key}']
        run_args += ['-e', 'TRAMO_PACKS=all']
        # Panel call-back (SERVERKIT_URL/SERVERKIT_API_KEY consumed by the
        # @tramo/serverkit pack via env fallback).
        url = callback_url or f'http://host.docker.internal:{cls._panel_port()}'
        run_args += ['-e', f'SERVERKIT_URL={url}']
        if callback_api_key:
            run_args += ['-e', f'SERVERKIT_API_KEY={callback_api_key}']
        # Pack credentials (decrypted from the config store).
        for name, value in cls.get_pack_secrets().items():
            run_args += ['-e', f'{name}={value}']
        run_args += [IMAGE]
        return run_args

    @classmethod
    def uninstall(cls, keep_data=True):
        """Remove the container; optionally delete the data directory."""
        if cls._is_windows():
            return {'success': False,
                    'error': 'The Automations extension is not supported on Windows.'}
        res = cls._docker(['rm', '-f', CONTAINER_NAME])
        if not res.get('success'):
            # A missing container is not an error for uninstall.
            if 'No such container' not in (res.get('error') or ''):
                return {'success': False,
                        'error': res.get('error', 'Failed to remove the tramo container')}
        if not keep_data:
            rm = run_privileged(['rm', '-rf', DATA_DIR])
            if getattr(rm, 'returncode', 1) != 0:
                return {'success': True,
                        'warning': f'Container removed but data at {DATA_DIR} could '
                                   f'not be deleted: {(getattr(rm, "stderr", "") or "").strip()}'}
        cls._save_config({'api_key': None})
        return {'success': True,
                'message': 'Automations engine removed'
                           + ('' if keep_data else ' (data deleted)')}

    @classmethod
    def control(cls, action):
        """Start / stop / restart the managed container."""
        if action not in ('start', 'stop', 'restart'):
            return {'success': False, 'error': f'Invalid action: {action!r}'}
        if not cls.is_installed():
            return {'success': False, 'error': 'The Automations engine is not installed.'}
        res = cls._docker([action, CONTAINER_NAME], timeout=60)
        if not res.get('success'):
            return {'success': False, 'error': res.get('error', f'docker {action} failed')}
        return {'success': True, 'message': f'Automations engine {action}ed', 'action': action}
