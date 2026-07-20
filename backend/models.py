"""Data models for the serverkit-tramo (Automations) extension.

Two tables, both namespaced ``ext_serverkit_tramo_*`` (dash -> underscore) so
``--purge`` on uninstall drops exactly these:

* :class:`TramoWorkflow` — a workflow *document* the panel owns. The ``doc``
  column holds a tramo ``WorkflowDoc`` (plain JSON) edited in the browser; the
  ``slug`` doubles as the server-side workflow id and the ``<slug>.json``
  filename materialized into the container's bind-mounted workflows dir.
* :class:`TramoRun` — a persisted summary of one execution, harvested from the
  container's in-memory run ring (which evicts after 1000 runs) so run history
  survives a restart.

Registration mirrors the serverkit-k8s pattern: importing this module defines
the tables on the shared metadata as a side effect; the manifest's
``models: "models:register"`` then calls :func:`register` (a no-op passthrough)
and the platform runs ``db.create_all()``.
"""
import json
from datetime import datetime

from app import db


class TramoWorkflow(db.Model):
    __tablename__ = 'ext_serverkit_tramo_workflows'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    # Server-side workflow id + <slug>.json filename. Unique, URL-safe.
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)

    # tramo WorkflowDoc JSON (edited by the embedded editor).
    doc = db.Column(db.Text, nullable=True)

    enabled = db.Column(db.Boolean, default=True, nullable=False)
    # Bumped on every doc save so the editor/UI can detect stale state.
    doc_version = db.Column(db.Integer, default=1, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Stamped when this workflow was last materialized + deployed to the engine.
    deployed_at = db.Column(db.DateTime, nullable=True)
    # doc_version captured at the last deploy. Dirty detection compares this to
    # the live doc_version -- a version counter, not a timestamp, so the deploy
    # commit's own updated_at bump can't make a just-deployed row look dirty.
    deployed_version = db.Column(db.Integer, nullable=True)

    def get_doc(self):
        """Return the parsed WorkflowDoc (empty dict if unset/invalid)."""
        if not self.doc:
            return {}
        try:
            return json.loads(self.doc)
        except (ValueError, TypeError):
            return {}

    def set_doc(self, doc):
        """Store a WorkflowDoc (dict or JSON string)."""
        if doc is None:
            self.doc = None
        elif isinstance(doc, str):
            self.doc = doc
        else:
            self.doc = json.dumps(doc)

    def is_dirty(self):
        """True when an enabled workflow needs a (re)deploy.

        Dirty when it has never been deployed or its doc changed since the last
        deploy (``doc_version`` moved past ``deployed_version``). Disabled
        workflows are never dirty -- they materialize to nothing.
        """
        if not self.enabled:
            return False
        if not self.deployed_at:
            return True
        return (self.doc_version or 1) > (self.deployed_version or 0)

    def to_dict(self, include_doc=False):
        out = {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'enabled': self.enabled,
            'doc_version': self.doc_version,
            'dirty': self.is_dirty(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'deployed_at': self.deployed_at.isoformat() if self.deployed_at else None,
        }
        if include_doc:
            out['doc'] = self.get_doc()
        return out


class TramoRun(db.Model):
    __tablename__ = 'ext_serverkit_tramo_runs'

    id = db.Column(db.Integer, primary_key=True)
    # tramo's own run id (from GET /api/runs). Unique so harvest upserts.
    run_id = db.Column(db.String(255), unique=True, nullable=False, index=True)
    workflow_slug = db.Column(db.String(255), nullable=True, index=True)
    status = db.Column(db.String(32), nullable=True)  # running|success|failed|suspended...
    source = db.Column(db.String(32), nullable=True)  # api|webhook|cron|replay
    error = db.Column(db.Text, nullable=True)

    usage = db.Column(db.Text, nullable=True)               # JSON token/cost usage
    pending_approvals = db.Column(db.Text, nullable=True)   # JSON list
    raw = db.Column(db.Text, nullable=True)                 # full run JSON as returned

    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def _json(self, value):
        if not value:
            return None
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return None

    def to_dict(self):
        return {
            'id': self.id,
            'run_id': self.run_id,
            'workflow_slug': self.workflow_slug,
            'status': self.status,
            'source': self.source,
            'error': self.error,
            'usage': self._json(self.usage),
            'pending_approvals': self._json(self.pending_approvals) or [],
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


def register(db):  # noqa: A002 - signature dictated by the platform (fn(db))
    """No-op passthrough required by the manifest ``models: "models:register"``.

    Importing this module already defined the tables on ``db.metadata``; the
    platform runs ``db.create_all()``. Nothing else to do here.
    """
    return [TramoWorkflow, TramoRun]
