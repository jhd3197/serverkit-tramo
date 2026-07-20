// Node registry for the tramo editor.
//
// tramo ships its node definitions as "packs": the built-in pack plus one pack
// per brand integration. `combinePacks` merges them into a single registry of
// editor-side node definitions (`.nodes`) and runtime executors (`.executors`).
// The editor only needs `.nodes` — executors run server-side inside the managed
// tramo container, never in the browser.
//
// This module is imported by TramoEditor.jsx (the lazy chunk) so all of these
// integration packs code-split into the editor bundle and never reach the
// panel's entry bundle.
import { combinePacks, BUILTIN_PACK } from 'tramo/runtime';

import gmail from 'tramo/integrations/gmail';
import github from 'tramo/integrations/github';
import telegram from 'tramo/integrations/telegram';
import discord from 'tramo/integrations/discord';
import notion from 'tramo/integrations/notion';
import openai from 'tramo/integrations/openai';
import anthropic from 'tramo/integrations/anthropic';
import linear from 'tramo/integrations/linear';
import airtable from 'tramo/integrations/airtable';
import stripe from 'tramo/integrations/stripe';
import cloudflare from 'tramo/integrations/cloudflare';
import googleDrive from 'tramo/integrations/google-drive';
import googleSheets from 'tramo/integrations/google-sheets';
import googleTasks from 'tramo/integrations/google-tasks';
import outlook from 'tramo/integrations/outlook';
import postgres from 'tramo/integrations/postgres';
import twilio from 'tramo/integrations/twilio';
import youtube from 'tramo/integrations/youtube';
import x from 'tramo/integrations/x';
import trello from 'tramo/integrations/trello';
import box from 'tramo/integrations/box';

// TODO(plan45): add SERVERKIT_PACK once @tramo/serverkit is published. Its
// executors run server-side; the editor only needs its node definitions here.

// Order matters only for the palette; combinePacks throws on id collisions, so
// the brand packs are all distinct by construction.
export const combined = combinePacks([
    BUILTIN_PACK,
    gmail,
    github,
    telegram,
    discord,
    notion,
    openai,
    anthropic,
    linear,
    airtable,
    stripe,
    cloudflare,
    googleDrive,
    googleSheets,
    googleTasks,
    outlook,
    postgres,
    twilio,
    youtube,
    x,
    trello,
    box,
]);

// The editor-side registry of node definitions. Pass straight to useWorkflow.
export const registry = combined.nodes;

export default registry;
