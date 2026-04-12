# TierListBot Bot

TierListBot is a Discord bot for creating and sharing tier lists with uploaded images.

## Features
- Slash-command first (`/tierlist ...` and `/bot status`).
- SQLite persistence for lists and items.
- Local image storage with validation and hashed filenames.
- Tier board PNG rendering via Pillow.
- top.gg guild count stats posting.
- Permission rule: list owner and server admins can edit; everyone can view/render.

## Commands
- `/tierlist create name:<string> [template:<string>]`
- `/tierlist add list_id:<string> image:<attachment> [label:<string>]`
- `/tierlist move list_id:<string> item_id:<string> tier:<S|A|B|C|D>`
- `/tierlist render list_id:<string>`
- `/tierlist show list_id:<string>`
- `/tierlist delete list_id:<string>`
- `/bot status`

## Components & Modals
- Quick tier move buttons after item upload.
- Manage view buttons for list rename and item relabel modals.
- Save board image button.

## Local Setup
1. Create and activate a virtual environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy env file:
   ```bash
   cp .env.example .env
   ```
4. Fill `.env` values.
5. Run the bot:
   ```bash
   python -m TierListBot
   ```

## Testing
```bash
pytest -q
```

## Project Layout
- `TierListBot/config.py`: env settings loader.
- `TierListBot/bot.py`: app bootstrap and command sync.
- `TierListBot/cogs/`: slash commands, components, modals.
- `TierListBot/services/`: DB, domain logic, image storage, renderer, top.gg.
- `docs/topgg_publish_checklist.md`: submission prep checklist.

## Discord Developer Application Notes
Use OAuth2 invite with scopes:
- `bot`
- `applications.commands`

Invite URL format:

```text
https://discord.com/oauth2/authorize?client_id=<DISCORD_APPLICATION_ID>&scope=bot%20applications.commands&permissions=274877975552
```
