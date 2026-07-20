"""ServerKit Automations extension backend package (tramo engine).

Embeds tramo (github.com/jhd3197/tramo) as the panel's workflow-automation
surface. The panel is the system of record for workflow docs; a managed
``@tramo/server`` Docker container on the panel host is the executor. See
docs/plans/45_TRAMO_AUTOMATIONS_EXTENSION_PLAN.md.
"""
from .tramo import tramo_bp

__all__ = ['tramo_bp']
