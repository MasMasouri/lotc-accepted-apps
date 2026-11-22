# LotC Accepted Apps → Discord

Every 15 minutes, GitHub Actions checks
https://www.lordofthecraft.net/apply/new/accepted/ and posts each newly accepted
application to a Discord channel. Each post includes the IGN, a link to the app, the Discord handle from the app, the character name and race, and the timezone.

## Setup
1. **Make the webhook.** In Discord, open the channel's settings and go to Integrations, then Webhooks, then New Webhook. Click Copy Webhook URL.
2. **Add it to GitHub.** In this repo, go to Settings, then Secrets and variables, then Actions, then New repository secret.
   Name it `DISCORD_WEBHOOK_URL` and paste the link as the value.
3. **Run it once.** Go to Actions, then Check LotC accepted apps, then Run workflow.
   The first run records the apps that are already accepted and doesn't post them. After that, new ones get posted.

The webhook link works like a password, so keep it only in the secret and never in the code.
