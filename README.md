# TierListBot

A Discord bot for creating and sharing tier lists with uploaded images — entirely inside Discord.

## Features

- Live board: creating a list posts a rendered image to the channel and updates it in-place as items are added
- Shorthand commands `/s` `/a` `/b` `/c` `/d` for fast image uploads
- Custom tiers with word-wrapped labels and automatic color assignment
- Interactive rearrange UI (pick item + destination tier from dropdowns)
- One active list per channel; history of finished lists
- SQLite persistence, local image storage, Pillow-rendered PNG boards
- Optional top.gg guild count reporting

## Commands

| Command | Description |
|---|---|
| `/tl start name:<string>` | Start a new tier list and post the live board |
| `/s image:<file>` | Add image to S tier |
| `/a image:<file>` | Add image to A tier |
| `/b image:<file>` | Add image to B tier |
| `/c image:<file>` | Add image to C tier |
| `/d image:<file>` | Add image to D tier |
| `/tl add image:<file>` | Add image and pick the tier from buttons |
| `/tl add-tier name:<label>` | Add a custom tier row |
| `/tl edit-tiers` | Open a text editor to add, remove, or reorder all tiers |
| `/tl rearrange` | Move an item to a different tier via dropdowns |
| `/tl show` | Re-post the board publicly |
| `/tl finish` | Mark the list complete and free the channel |
| `/tl delete` | Permanently delete the active list |
| `/tl history` | Browse and re-render finished lists |
| `/tl help` | Show command reference |

All `/tl` commands are also available as `/tierlist`.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy and fill the env file:
   ```bash
   cp .env.example .env
   ```
4. Run:
   ```bash
   python -m TierListBot
   ```

## Testing

```bash
pytest -q
```

## Project Layout

- `TierListBot/config.py` — env settings loader
- `TierListBot/bot.py` — app bootstrap and command sync
- `TierListBot/cogs/` — slash commands, views, modals
- `TierListBot/services/` — DB, domain logic, image storage, renderer, top.gg

## Invite

OAuth2 scopes: `bot` + `applications.commands`

```
https://discord.com/oauth2/authorize?client_id=<DISCORD_APPLICATION_ID>&scope=bot%20applications.commands&permissions=274877975552
```
