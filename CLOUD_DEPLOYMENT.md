# Cloud Deployment Guide

Your motorcycle bot is ready to deploy! Choose either Railway or Render (both have free tiers).

---

## Option 1: Railway.app (Recommended - Easiest)

### Step 1: Create GitHub Repository
1. Go to https://github.com/new
2. Create a new repository (name it "motorcycle-bot" or similar)
3. **DON'T** initialize with README (we already have files)
4. Click "Create repository"

### Step 2: Push Your Code to GitHub
Run these commands in your terminal:

```bash
cd C:\Users\mkari\motorcycle_bot
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
git branch -M main
git push -u origin main
```

Replace `YOUR_USERNAME` and `YOUR_REPO_NAME` with your actual GitHub username and repo name.

### Step 3: Deploy to Railway
1. Go to https://railway.app and sign up (use GitHub login)
2. Click "New Project" → "Deploy from GitHub repo"
3. Select your motorcycle-bot repository
4. Railway will auto-detect it's a Python app

### Step 4: Add Environment Variables
In Railway dashboard:
1. Click on your project
2. Go to "Variables" tab
3. Add these variables:
   - `TELEGRAM_BOT_TOKEN` = `8277158161:AAGPpCxXIRvV5sJ_H_zKSopvJ5uErHqkAFs`
   - `TELEGRAM_CHAT_ID` = `844726737`

### Step 5: Deploy!
Railway will automatically build and deploy. Check the "Deployments" tab to see progress.

**Done!** Your bot is now running 24/7 on Railway's free tier.

---

## Option 2: Render.com (Also Free)

### Step 1-2: Same as Railway
Follow Steps 1-2 from Railway instructions above to push to GitHub.

### Step 3: Deploy to Render
1. Go to https://render.com and sign up
2. Click "New +" → "Background Worker"
3. Connect your GitHub repository
4. Render will auto-detect the `render.yaml` configuration

### Step 4: Add Environment Variables
1. In the dashboard, go to "Environment"
2. Add:
   - `TELEGRAM_BOT_TOKEN` = `8277158161:AAGPpCxXIRvV5sJ_H_zKSopvJ5uErHqkAFs`
   - `TELEGRAM_CHAT_ID` = `844726737`

### Step 5: Deploy!
Click "Create Background Worker" and Render will deploy your bot.

---

## Verify It's Working

After deployment:
1. Check the logs in Railway/Render dashboard
2. You should see: "🏍️ Motorcycle Deal Bot starting up..."
3. You'll get a Telegram message saying the bot is running
4. The bot will check Facebook Marketplace every 15 minutes

---

## Monitoring & Logs

- **Railway**: Click your project → "Deployments" → View logs
- **Render**: Dashboard → Your service → "Logs" tab

---

## Making Changes Later

If you want to change search location, price range, etc:

1. Edit `bot.py` in your local folder
2. Commit and push:
   ```bash
   cd C:\Users\mkari\motorcycle_bot
   git add bot.py
   git commit -m "Updated search settings"
   git push
   ```
3. Railway/Render will auto-deploy the changes

---

## Free Tier Limits

**Railway**: 500 hours/month (plenty for 24/7), $5 credit/month
**Render**: 750 hours/month free

Both are more than enough for this bot!

---

## Troubleshooting

**"Deployment failed"**: Check logs for errors. Usually means Playwright needs dependencies.

**"No messages received"**: Verify your environment variables are set correctly in the dashboard.

**"Out of memory"**: Unlikely with this bot, but you can upgrade to a paid plan if needed.

---

Need help? Check the logs first - they'll show exactly what's happening!
