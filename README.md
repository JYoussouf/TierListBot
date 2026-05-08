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
| `/s` `/a` `/b` `/c` `/d` | Add an image to that tier |
| `/tl add` | Add image + pick tier from buttons |
| `/tl add-tier name:…` | Add a custom tier row |
| `/tl edit-tiers` | Reorder / add / remove all tiers at once |
| `/tl rearrange` | Move an item to a different tier |
| `/tl show` | Delete old board and re-post it at the bottom of chat |
| `/tl finish` | Close the list, frees the channel |
| `/tl delete` | Permanently delete it |
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
