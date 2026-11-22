# LotC Applications → Discord

Every 15 minutes, GitHub Actions checks Lord of the Craft's whitelist applications and posts to a Discord channel:

- **📥 New Application**: an app was submitted (it shows up in the main list at /apply/new/ as Pending or Under Review)
- **✅ Application Accepted**: an app moved to /apply/new/accepted/

Each post shows the IGN, Discord handle, character, timezone, and a **View Application** link.

## Setup
1. **Make the webhook.** In Discord, open the channel's settings and go to Integrations → Webhooks → New Webhook. Click Copy Webhook URL.
2. **Add it to GitHub.** In this repo, go to Settings → Secrets and variables → Actions → New repository secret.
   Name it `DISCORD_WEBHOOK_URL` and paste the link as the value.
3. **Run it once.** Go to Actions → Check LotC applications → Run workflow.
   The first run records the apps that are already there and doesn't post them.

## Test posts
Go to Actions → Check LotC applications → Run workflow, and tick **Send test posts**. This re-posts the newest pending app and the newest accepted app, each marked "test post" in the footer.

The webhook link works like a password, so keep it only in the secret and never in the code.
