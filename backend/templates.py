"""Starter workflow templates (serverkit-tramo / Automations extension, Phase 3).

A small set of seed :class:`WorkflowDoc` fixtures the Workflows tab offers as
"New from template", so a fresh install has something runnable to start from.
These are node-vocabulary sketches for the embedded editor -- the operator fills
in credentials (pack secrets) and adjusts nodes before deploying.

Kept as plain Python dicts (not files) so they ship with the backend package and
need no bundling. Each template's ``doc`` is a minimal tramo WorkflowDoc.
"""

STARTER_TEMPLATES = [
    {
        'id': 'backup-failed-telegram',
        'name': 'Backup failed -> Telegram',
        'description': 'When a panel backup fails, send a Telegram message.',
        'doc': {
            'name': 'Backup failed -> Telegram',
            'nodes': [
                {'id': 'trigger', 'type': 'webhook-trigger:serverkit:event',
                 'position': {'x': 80, 'y': 120},
                 'config': {'path': '/sk/events'}},
                {'id': 'filter', 'type': 'if',
                 'position': {'x': 360, 'y': 120},
                 'config': {'expression': "{{trigger.body.event}} == 'backup.restored'"}},
                {'id': 'notify', 'type': 'telegram:send-message',
                 'position': {'x': 640, 'y': 120},
                 'config': {'text': 'A ServerKit backup event fired: {{trigger.body.event}}'}},
            ],
            'edges': [
                {'id': 'e1', 'source': 'trigger', 'target': 'filter'},
                {'id': 'e2', 'source': 'filter', 'target': 'notify'},
            ],
        },
    },
    {
        'id': 'nightly-health-github',
        'name': 'Nightly health ping -> GitHub issue',
        'description': 'On a nightly cron, check something and open a GitHub issue on failure.',
        'doc': {
            'name': 'Nightly health ping -> GitHub issue',
            'nodes': [
                {'id': 'cron', 'type': 'cron-trigger',
                 'position': {'x': 80, 'y': 120},
                 'config': {'cron': '0 3 * * *'}},
                {'id': 'ping', 'type': 'http-request',
                 'position': {'x': 360, 'y': 120},
                 'config': {'method': 'GET', 'url': 'https://example.com/health'}},
                {'id': 'issue', 'type': 'github:create-issue',
                 'position': {'x': 640, 'y': 120},
                 'config': {'title': 'Nightly health check failed',
                            'body': 'The nightly health ping did not pass.'}},
            ],
            'edges': [
                {'id': 'e1', 'source': 'cron', 'target': 'ping'},
                {'id': 'e2', 'source': 'ping', 'target': 'issue'},
            ],
        },
    },
    {
        'id': 'panel-event-discord',
        'name': 'Panel event -> Discord webhook',
        'description': 'Relay any panel event to a Discord channel via webhook.',
        'doc': {
            'name': 'Panel event -> Discord webhook',
            'nodes': [
                {'id': 'trigger', 'type': 'webhook-trigger:serverkit:event',
                 'position': {'x': 80, 'y': 120},
                 'config': {'path': '/sk/events'}},
                {'id': 'discord', 'type': 'discord:send-message',
                 'position': {'x': 400, 'y': 120},
                 'config': {'content': 'ServerKit event: {{trigger.body.event}}'}},
            ],
            'edges': [
                {'id': 'e1', 'source': 'trigger', 'target': 'discord'},
            ],
        },
    },
]


def list_templates(include_doc=False):
    """Template summaries (or full docs when include_doc)."""
    out = []
    for t in STARTER_TEMPLATES:
        entry = {'id': t['id'], 'name': t['name'], 'description': t['description']}
        if include_doc:
            entry['doc'] = t['doc']
        out.append(entry)
    return out


def get_template(template_id):
    for t in STARTER_TEMPLATES:
        if t['id'] == template_id:
            return t
    return None
