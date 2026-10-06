"""Official bot account only; no history scraping or public data endpoint."""
import asyncio
import contextlib
import logging
import os
import json
from pathlib import Path
import signal

import discord
from aiohttp import web
from core import Scope, Store


async def main():
    scope = Scope.environment()
    enabled = os.getenv('COLLECTION_ENABLED', 'false').lower() == 'true'
    token = os.getenv('DISCORD_BOT_TOKEN', '').strip()
    enumerate_scope = os.getenv('ENUMERATE_CURRENT_SCOPE', 'false').lower() == 'true'
    snapshot = Path(os.getenv('SCOPE_SNAPSHOT_PATH', 'data/scope.json'))
    pending_snapshot = enumerate_scope and not snapshot.exists() and len(scope.guilds) == 1
    if enabled and (not token or (not pending_snapshot and not all((scope.users, scope.guilds, scope.channels)))):
        raise ValueError('Collection requires bot token and all three explicit allowlists')
    store = Store(os.getenv('DATA_PATH', 'data/messages.sqlite3'), scope,
                  int(os.getenv('RETENTION_DAYS', '7')), int(os.getenv('MAX_MESSAGES', '10000')))
    intents = discord.Intents.none()
    intents.members = enumerate_scope
    intents.guilds = True
    intents.guild_messages = True
    intents.message_content = True
    client = discord.Client(intents=intents, max_messages=None)
    state = {'mode': 'disabled' if not enabled else 'connecting'}

    @client.event
    async def on_ready():
        nonlocal scope, pending_snapshot
        if pending_snapshot:
            state['mode'] = 'configuring'
            guild = client.get_guild(next(iter(scope.guilds)))
            if guild is None:
                state['mode'] = 'server_unavailable'
                return
            try:
                users = frozenset([member.id async for member in guild.fetch_members(limit=None) if not member.bot])
                channels = frozenset(channel.id for channel in [*guild.channels, *guild.threads]
                                     if channel.permissions_for(guild.me).view_channel)
                if not users or not channels:
                    raise ValueError('Empty server scope')
                saved = {'users': sorted(users), 'guilds': sorted(scope.guilds), 'channels': sorted(channels)}
                snapshot.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                temporary = snapshot.with_suffix('.tmp')
                temporary.write_text(json.dumps(saved))
                temporary.chmod(0o600)
                temporary.replace(snapshot)
                scope = Scope(users, scope.guilds, channels)
                store.scope = scope
                pending_snapshot = False
            except Exception:
                state['mode'] = 'scope_configuration_failed'
                return
        state['mode'] = 'connected'

    @client.event
    async def on_resumed():
        state['mode'] = 'connected' if not pending_snapshot else 'configuring'

    @client.event
    async def on_disconnect():
        state['mode'] = 'disconnected'

    @client.event
    async def on_error(event, *args, **kwargs):
        state['mode'] = 'event_error'
        stop.set()

    @client.event
    async def on_message(message):
        if state['mode'] != 'connected' or not message.guild or message.webhook_id:
            return
        store.add(message.id, message.author.id, message.guild.id, message.channel.id,
                  message.created_at.timestamp(), message.content, message.author.bot)

    @client.event
    async def on_raw_message_edit(payload):
        if payload.guild_id in scope.guilds and payload.channel_id in scope.channels and 'content' in payload.data:
            store.edit(payload.message_id, payload.guild_id, payload.channel_id, payload.data['content'])

    @client.event
    async def on_raw_message_delete(payload):
        store.delete([payload.message_id])

    @client.event
    async def on_raw_bulk_message_delete(payload):
        store.delete(payload.message_ids)

    async def health(request):
        return web.json_response({'status': 'ok', 'collection': state['mode']}, headers={'Cache-Control': 'no-store'})

    app = web.Application()
    app.router.add_get('/healthz', health)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', '10000'))).start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    async def prune_loop():
        while True:
            store.prune()
            await asyncio.sleep(300)

    prune_task = asyncio.create_task(prune_loop())
    stop_task = asyncio.create_task(stop.wait())
    bot_task = asyncio.create_task(client.start(token)) if enabled else None
    try:
        tasks = [stop_task, prune_task] + ([bot_task] if bot_task else [])
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()  # Unexpected failures stop the process instead of appearing healthy.
    finally:
        await client.close()
        for task in (bot_task, prune_task, stop_task):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        await runner.cleanup()
        store.db.close()


if __name__ == '__main__':
    # Discord exceptions can contain request details: do not emit raw diagnostics.
    logging.disable(logging.CRITICAL)
    try:
        asyncio.run(main())
    except Exception:
        print('Service stopped. Check bot credentials, intents, allowlists, and storage configuration.', flush=True)
        raise SystemExit(1)
