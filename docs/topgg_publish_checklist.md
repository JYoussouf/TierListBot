# top.gg Publish Checklist (TierListBot v1)

## Discord Application Setup
- [ ] Create Discord Developer Application and Bot user.
- [ ] Enable required intents (Guilds intent is enough for v1).
- [ ] Set `DISCORD_APPLICATION_ID` and `DISCORD_TOKEN`.
- [ ] Invite bot with scopes: `bot applications.commands`.
- [ ] Recommended permissions integer: `274877975552` (send messages, embed links, attach files, use slash commands).

Invite URL template:

```text
https://discord.com/oauth2/authorize?client_id=<DISCORD_APPLICATION_ID>&scope=bot%20applications.commands&permissions=274877975552
```

## Listing Metadata
- [ ] Bot short description and long description.
- [ ] Prefix note: slash-command only bot.
- [ ] Command help summary (`/tierlist create`, `/tierlist add`, `/tierlist move`, `/tierlist render`, `/tierlist show`, `/tierlist delete`, `/bot status`).
- [ ] Support server URL configured in `.env`.
- [ ] Terms of Service URL published.
- [ ] Privacy Policy URL published.

## API Integration
- [ ] Set `TOPGG_API_TOKEN` and `TOPGG_BOT_ID`.
- [ ] Confirm periodic guild stats posting succeeds.
- [ ] Validate logs show successful `post_stats` calls.

## Manual QA Before Submit
- [ ] In a test guild: full create -> add -> move -> render flow works.
- [ ] Images persist across bot restarts.
- [ ] Permission behavior: owner/admin can edit, others can only view/render.
- [ ] `/bot status` returns healthy output.
