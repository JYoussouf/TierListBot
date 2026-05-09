# TierListBot

Discord bot for group tier lists. Posts a live board image to the channel that updates in place as people add images.

## Running

```bash
cp .env.example .env  # fill in DISCORD_TOKEN, DISCORD_APPLICATION_ID
python -m TierListBot
```

Set `DISCORD_GUILD_ID` for instant guild-scoped command sync during dev. Leave it blank for global sync in prod.

## Commands

| Command | What it does |
|---|---|
| `/tl start name:…` | Start a new list, posts the board |
| `/tl add` | Upload an image and pick the tier from buttons |
| `/tl add-text text:…` | Add a text tile (white text on black square) |
| `/tl edit-tiers` | Add, remove, or reorder all tiers at once |
| `/tl rearrange` | Pick an item, nudge it with arrows, then click Update to apply or Delete item to remove |
| `/tl show` | Delete old board and re-post it at the bottom of chat |
| `/tl finish` | Close the list, frees the channel |
| `/tl delete-current-list` | Permanently delete it |
| `/tl history` | Re-render past lists |

`/tl` and `/tierlist` are interchangeable.

## Tests

```bash
pytest -q
```

## Invite URL

```
https://discord.com/oauth2/authorize?client_id=<DISCORD_APPLICATION_ID>&scope=bot%20applications.commands&permissions=274877975552
```
