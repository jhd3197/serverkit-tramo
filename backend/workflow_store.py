"""Workflow document store (serverkit-tramo / Automations extension).

CRUD over :class:`TramoWorkflow` rows plus the two engine-facing operations:

* :meth:`WorkflowStore.materialize` — write every *enabled* workflow's doc as
  ``<slug>.json`` into the container's bind-mounted workflows dir and prune the
  files of disabled/deleted workflows.
* :meth:`WorkflowStore.deploy` — materialize, then restart the container so
  ``@tramo/server`` re-reads the dir (it loads workflows once at boot), then
  stamp ``deployed_at`` on the enabled rows.

File I/O goes through small choke-point classmethods (``_write_file`` /
``_remove_file`` / ``_list_files``) so it stays privileged (the data dir is
root-owned) and mockable in tests.
"""
import json
import logging
import os
import re
import tempfile

from app import db

from .models import TramoWorkflow
from .host_service import TramoHostService, HOST_WORKFLOWS_DIR

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r'[^a-z0-9]+')


def slugify(value):
    """Lowercase, hyphenated, URL/filename-safe slug."""
    base = _SLUG_RE.sub('-', (value or '').strip().lower()).strip('-')
    return base or 'workflow'


class WorkflowStore:
    """DB CRUD + engine materialization for automation workflows."""

    # ---------- CRUD ----------

    @classmethod
    def list_workflows(cls):
        rows = TramoWorkflow.query.order_by(TramoWorkflow.updated_at.desc()).all()
        return [w.to_dict() for w in rows]

    @classmethod
    def get(cls, slug):
        return TramoWorkflow.query.filter_by(slug=slug).first()

    @classmethod
    def _unique_slug(cls, name, ignore_id=None):
        base = slugify(name)
        candidate = base
        n = 2
        while True:
            existing = TramoWorkflow.query.filter_by(slug=candidate).first()
            if not existing or existing.id == ignore_id:
                return candidate
            candidate = f'{base}-{n}'
            n += 1

    @classmethod
    def create(cls, name, doc=None, enabled=True):
        name = (name or '').strip()
        if not name:
            raise ValueError('A workflow name is required')
        wf = TramoWorkflow(
            name=name,
            slug=cls._unique_slug(name),
            enabled=bool(enabled),
            doc_version=1,
        )
        wf.set_doc(doc if doc is not None else cls._empty_doc(wf.slug, name))
        db.session.add(wf)
        db.session.commit()
        return wf

    @classmethod
    def update(cls, slug, name=None, doc=None, enabled=None):
        wf = cls.get(slug)
        if not wf:
            raise ValueError('Workflow not found')
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError('A workflow name is required')
            wf.name = name
        if enabled is not None:
            wf.enabled = bool(enabled)
        if doc is not None:
            wf.set_doc(doc)
            wf.doc_version = (wf.doc_version or 1) + 1
        db.session.commit()
        return wf

    @classmethod
    def delete(cls, slug):
        wf = cls.get(slug)
        if not wf:
            raise ValueError('Workflow not found')
        db.session.delete(wf)
        db.session.commit()
        # Best-effort prune the materialized file.
        try:
            cls._remove_file(slug)
        except Exception as e:  # noqa: BLE001
            logger.debug('could not remove workflow file for %s: %s', slug, e)
        return True

    @staticmethod
    def _empty_doc(slug, name):
        """A minimal valid tramo WorkflowDoc so a new workflow opens cleanly.

        Mirrors tramo's own ``emptyDoc()`` — ``version`` and ``meta`` must be
        present, since the editor's Canvas reads ``doc.meta.mcpServers``
        unconditionally and crashes on a doc without ``meta``.
        """
        return {
            'version': 1,
            'id': slug,
            'name': name,
            'nodes': [],
            'edges': [],
            'meta': {},
        }

    # ---------- engine materialization ----------

    @classmethod
    def _write_file(cls, slug, doc):
        """Write ``<slug>.json`` into the workflows dir (privileged). Linux-only."""
        if os.name == 'nt':
            return
        payload = json.dumps(doc, indent=2)
        dest = f'{HOST_WORKFLOWS_DIR}/{slug}.json'
        from app.utils.system import run_privileged
        run_privileged(['mkdir', '-p', HOST_WORKFLOWS_DIR])
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as tmp:
            tmp.write(payload)
            tmp_path = tmp.name
        try:
            run_privileged(['cp', tmp_path, dest])
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    @classmethod
    def _remove_file(cls, slug):
        if os.name == 'nt':
            return
        from app.utils.system import run_privileged
        run_privileged(['rm', '-f', f'{HOST_WORKFLOWS_DIR}/{slug}.json'])

    @classmethod
    def _list_files(cls):
        """Slugs currently materialized in the workflows dir."""
        if os.name == 'nt':
            return []
        from app.utils.system import run_privileged
        res = run_privileged(['ls', '-1', HOST_WORKFLOWS_DIR])
        if getattr(res, 'returncode', 1) != 0:
            return []
        out = getattr(res, 'stdout', '') or ''
        return [line[:-5] for line in out.splitlines()
                if line.strip().endswith('.json')]

    @classmethod
    def materialize(cls):
        """Write enabled docs, prune the rest. Returns a summary dict."""
        enabled = TramoWorkflow.query.filter_by(enabled=True).all()
        enabled_slugs = {w.slug for w in enabled}
        written = []
        for wf in enabled:
            cls._write_file(wf.slug, wf.get_doc())
            written.append(wf.slug)
        pruned = []
        for slug in cls._list_files():
            if slug not in enabled_slugs:
                cls._remove_file(slug)
                pruned.append(slug)
        return {'written': written, 'pruned': pruned}

    @classmethod
    def deploy(cls):
        """Materialize + restart the engine + stamp ``deployed_at``.

        Restart is required because ``@tramo/server`` reads the workflows dir
        only at boot (no reload endpoint yet). The checkpoint store preserves any
        suspended runs across the restart.
        """
        from datetime import datetime

        if not TramoHostService.is_installed():
            return {'success': False,
                    'error': 'The Automations engine is not installed. Install it '
                             'from the Automations Settings tab first.'}
        summary = cls.materialize()
        restart = TramoHostService.control('restart')
        if not restart.get('success'):
            return {'success': False,
                    'error': restart.get('error', 'Failed to restart the engine'),
                    'materialized': summary}
        now = datetime.utcnow()
        for wf in TramoWorkflow.query.filter_by(enabled=True).all():
            wf.deployed_at = now
            wf.deployed_version = wf.doc_version
        db.session.commit()
        return {'success': True, 'message': 'Automations deployed', 'materialized': summary}
