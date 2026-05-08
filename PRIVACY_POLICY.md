# TierListBot - Privacy Policy

_Last updated: 2026-05-08_

---

## 1. Data We Collect

TierListBot stores the following data in order to function:

- **Discord server (guild) ID** and **channel ID** - to track which channel a tier list belongs to
- **Discord user IDs** - to identify who created a list and who added or moved items
- **Uploaded images** - stored locally on the host server; the original filename, file size, content type, and a SHA-256 hash are also recorded
- **Tier list names, tier labels, item labels, and tier assignments** - the content of your lists
- **Audit log** - a record of every action taken on a list (create, add item, move item, edit tiers, finish, delete), including the user ID of who performed it and when

No message content, usernames, profile pictures, email addresses, or any other personal information is collected.

---

## 2. Why We Collect It

This data is used exclusively to operate the bot:

- Server and channel IDs are used to find the active tier list in a given channel
- User IDs are used to enforce edit permissions (only the list owner or a server admin can modify a list)
- Uploaded images are stored so they can be rendered into the board image
- The audit log exists for debugging and moderation purposes

None of this data is sold, shared with third parties, or used for advertising.

---

## 3. How Your Data Is Protected

All data is stored locally on the server running the bot. It is not transmitted to any external service except Discord (to post and update board images) and optionally top.gg (guild count only, no user data).

---

## 4. Requesting Data Deletion

To have your data removed:

- **Delete a tier list**: use `/tl delete` - this removes all items and images associated with that list immediately
- **Request full removal**: open an issue on the project repository and the data will be wiped manually

Deletion is permanent and cannot be undone.

---

## 5. Contact

For questions or data requests, open an issue on the project repository.
