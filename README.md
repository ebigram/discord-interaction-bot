# Discord interaction bot

Minimal official Discord bot for your own interaction analysis. Python 3.12, discord.py, SQLite, and a Render health endpoint. Collection is disabled by default. The public repository contains code only; never commit tokens, IDs, or collected data.

## Collection boundary

Every message must match ALL three exact allowlists: `ALLOWED_USER_IDS`, `ALLOWED_GUILD_IDS`, and `ALLOWED_CHANNEL_IDS` (comma-separated numeric IDs). Empty lists admit nothing. Threads require their own channel IDs; listing a parent does not include its threads. Discord must also grant the bot access. DMs, bots, webhooks, unlisted authors, channels, and servers are excluded. No historical backfill, user account login, commands, outgoing messages, or attachment downloads.

Only message ID, author ID, server ID, channel ID, creation time, and up to 4,000 characters of text are stored. Reply targets, usernames, attachments, embeds, reactions, and unrelated account data are not stored. Discord sends channel events to the bot before local filtering; excluded content is not retained. Text itself can contain sensitive information about other people; configure only appropriate channels and follow their rules.

Edits replace text only for already admitted records. Received deletion events remove records. Events missed during downtime cannot be reconciled; deleted messages may remain until retention expiry. The bot does not fetch deleted messages or history. Retention defaults to 7 days (1–30 allowed), capped at 10,000 rows (maximum 100,000), with pruning on each insert and every five minutes. Changing scope purges out-of-scope rows at startup. SQLite secure deletion is enabled; this is not a guarantee about disk snapshots/backups. Host storage is not application-encrypted.

No message content or IDs are logged. `/healthz` exposes only service/connection status; it never exposes data. There is no public export or analysis endpoint.

## Discord setup

1. In https://discord.com/developers/applications create an application and its **Bot** account.
2. Enable **Message Content Intent** in the Bot settings. Enable **Server Members Intent** only when using the explicitly authorized member enumeration option below. Presence Intent is unnecessary.
3. Install it in a server you administer or where an administrator authorizes it, with the `bot` scope and **View Channels** only. Restrict channel access with permission overrides. No Administrator, Send Messages, or Read Message History permission is needed for live collection.
4. Enable Discord Developer Mode and copy the desired user, server, and channel IDs.
5. In Render's Environment settings enter `DISCORD_BOT_TOKEN` directly, plus the three allowlists. Never paste a token into chat, code, or an issue. Set `COLLECTION_ENABLED=true` only when ready, and redeploy.

## Authorized current-server snapshot

With your explicit authorization, `ENUMERATE_CURRENT_SCOPE=true` enumerates all current non-bot members and accessible channels in the one configured server, once on the first authenticated startup. It writes concrete user/server/channel ID allowlists to `SCOPE_SNAPSHOT_PATH` (private persistent file). Collection remains blocked until that snapshot succeeds. The deployed server ID is configured privately in Render, not this repository.

This is a frozen scope: future members and future channels/threads are not automatically included. Existing threads depend on what Discord exposes to the bot at snapshot time. The bot must have Server Members Intent enabled to enumerate members. The bot never bypasses channel permissions. On restart it reads the saved allowlists; it does not silently expand them. To intentionally refresh the snapshot, disable collection, remove the private scope file, and then re-enable collection with enumeration enabled. To use manually entered allowlists instead, set enumeration false and populate all three ID variables. Member enumeration stores IDs only, with no names or member profiles.

## Render deployment

Build: `pip install -r requirements.txt`
Start: `python bot.py`
Health check: `/healthz`
Python: 3.12.8

`render.yaml` defines an always-on paid Starter service and a 1 GB persistent disk at `/var/data`, with collection off until configured. `DATA_PATH=/var/data/messages.sqlite3` must point to the mounted disk before enabling collection. Free services sleep after inactivity and lose local SQLite files on restarts, so they are not suitable for continuous collection. Run only one instance; a shared SQLite file is not a multi-instance datastore. Review Render's displayed cost first. A background worker with the same bot event logic is another paid option.

When enabled, `/healthz` returns `collection: connected` once Discord connects. `status: ok` alone does not prove Discord connection or collection. No live collection has been verified until an allowed test message is stored and an excluded test message is absent.

## Local use and private access

Create a virtual environment and install requirements. Set environment variables yourself (the program does not automatically load `.env`). Run `python bot.py`. With collection disabled it starts without a token. Tests: `python -m unittest -v`.

Access SQLite privately through your own host account/local filesystem; there is intentionally no public download route. Keep exports outside this repository. To stop collection set `COLLECTION_ENABLED=false` and redeploy; retention maintenance still runs. To erase all stored records, stop collection, remove the database and any associated files through private host access, and review any host snapshots separately. Revoking the token or channel access also stops future access.
