# Giveaway Bot

A persistent `discord.py` giveaway bot using the `🎉` reaction for entries.

## Setup

1. Install Python 3.10 or newer.
2. Create a bot in the [Discord Developer Portal](https://discord.com/developers/applications).
3. Enable the **Message Content Intent**, **Server Members Intent**, and **Message Content** access required by your bot.
4. Invite the bot with permissions to send messages, embed links, add reactions, read message history, and view channels.
5. Install dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

6. Copy `.env.example` to `.env` and set `DISCORD_TOKEN`.
7. Start the bot:

   ```bash
   python bot.py
   ```

Giveaway data is stored in `data/giveaways.json` and survives restarts.

## Commands

```text
!giveaway create <duration> <winner_count> <prize>
!giveaway info <giveaway_id>
!giveaway addentries <giveaway_id> @user <amount>
!giveaway end <giveaway_id>
!giveaway reroll <giveaway_id>
!giveaway setwinner <giveaway_id> @user [@user...]
```

Examples:

```text
!giveaway create 2h 1 $25 Gift Card
!giveaway addentries A1B2C3D4 @Alex 5
!giveaway setwinner A1B2C3D4 @Alex
```

The `addentries` command (also available as `boost`) gives a participant extra weighted entries while still requiring them to react to the giveaway. It does not create fake Discord reactions; Discord allows only one reaction per user. `end` and `setwinner` require the **Manage Server** permission.