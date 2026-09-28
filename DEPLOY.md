# Put AdPulse online for free (Render + Supabase)

When you finish, AdPulse will live at a web address like `https://adpulse-xxxx.onrender.com`.
You open it in any browser, on any device, with nothing to run on your computer.

- **Render** runs the website (free plan).
- **Supabase** stores the data (free plan).

This takes about 20 minutes. You don't need PowerShell.

---

## Step 1: Create the database in Supabase

1. Go to **supabase.com**, then **Dashboard → New project**.
2. Fill in:
   - **Name:** `adpulse`
   - **Database password:** click **Generate a password**. Then **copy it and keep it somewhere safe**, because you'll need it in a moment.
     (If you type your own, use only letters and numbers. Symbols like `@ # / ?` break the connection string.)
   - **Region:** **Southeast Asia (Singapore)**. It must be the same region as Render in Step 3, so pages load quickly.
3. Click **Create new project** and wait about 2 minutes.
4. Click the **Connect** button at the top of the project.
5. Choose **Session pooler**. Don't use "Direct connection", because Render's free plan can't reach it.
6. Copy the connection string. It looks like:
   ```
   postgresql://postgres.abcdefghij:[YOUR-PASSWORD]@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres
   ```
7. Replace `[YOUR-PASSWORD]` (including the square brackets) with your database password.
   Keep this full line handy for Step 3. **Don't share it**, because it gives full access to your data.

AdPulse creates its own tables the first time it starts. It keeps them in a private `adpulse` area
that Supabase's public web API doesn't expose.

## Step 2: Put the code on GitHub

1. Go to **github.com** and sign up or log in.
2. Click **+** (top right), then **New repository**.
   - **Name:** `adpulse`
   - Choose **Private**.
   - Click **Create repository**.
3. On the next page, click **uploading an existing file**.
4. Open your unzipped `adpulse` folder in File Explorer. Select everything inside it **except**:
   - the `.env` file (it holds your secrets)
   - the `data` folder (your local test data)
5. Drag the selected files and folders into the GitHub page, then click **Commit changes**.

## Step 3: Create the website on Render

1. Go to **render.com** and click **Get started**. Sign up **with GitHub** so it can see your repository.
2. Click **New +**, then **Blueprint**.
3. Pick your `adpulse` repository and click **Connect**.
4. Render reads the included `render.yaml` and asks for one value:
   - **DATABASE_URL:** paste the full Supabase line from Step 1.
5. Click **Apply** or **Deploy Blueprint**. The first build takes about 3–5 minutes.
6. When it says **Live**, click the address at the top (e.g. `https://adpulse-xxxx.onrender.com`).
7. AdPulse opens on **Set up**. Create your agency and owner login, and you're in.

Render creates the `SECRET_KEY` for you automatically. **Never change or delete it**, because it's what
unlocks the saved client logins.

## Step 4: Tell Google about your new address

In Google Cloud, go to **Google Auth Platform → Clients**, open your client, and under
**Authorised redirect URIs** click **Add URI**:

```
https://adpulse-xxxx.onrender.com/oauth/google/callback
```

Use your real Render address, then click **Save**. Do the same for Meta, TikTok and LinkedIn once you have those apps
(replace `google` in the address with `meta`, `tiktok` or `linkedin`).

## Step 5 (optional): Stop it falling asleep

On the free plan, the site goes to sleep after 15 minutes with no visitors. The next visit then takes
about a minute to load, and automatic syncing pauses while it's asleep.

To keep it awake for free:
1. Go to **cron-job.org** and create a free account.
2. Click **Create cronjob**.
   - **URL:** `https://adpulse-xxxx.onrender.com/healthz`
   - **Schedule:** every **10 minutes**
3. Save.

Render's free plan gives 750 hours a month, which is enough to keep one site awake all month.

Or, if you'd rather let it sleep, schedule just a daily data sync instead:
- **URL:** `https://adpulse-xxxx.onrender.com/tasks/sync?key=YOUR_CRON_SECRET`
- Find `CRON_SECRET` in Render under your service, then **Environment**.

---

## Step 6 (optional): Find competitors automatically

The **Competitors** tab can list similar businesses nearby with their Google ratings and review counts.

1. In **Google Cloud Console** (same project as before) go to **APIs & Services → Library**, search **Places API (New)** and click **Enable**. Google asks for a billing account; it includes a free monthly allowance, which is plenty for a few audits a day.
2. Go to **APIs & Services → Credentials → Create credentials → API key**. Copy the key. Click **Edit API key**, under **API restrictions** choose **Restrict key** and tick **Places API (New)**, then Save.
3. In **Render → adpulse → Environment → Add Environment Variable**: key `GOOGLE_PLACES_API_KEY`, value = the key. Click **Save, rebuild and deploy**.

Without the key, the tab still works: click **Open in Google Maps** and type in the top few competitors by hand.

## Step 7 (optional): Switch on the AI price review

The **Proposal & fees** tab has an **Ask AI to review these prices** button. It reads the audit, your packages, the price
check and market prices, and suggests which package to lead with, what to change and what to say. It uses Claude and costs
a few cents per review, paid to Anthropic.

1. Go to **console.anthropic.com**, sign up, then **Billing → Add credit** (US$5 is plenty to start).
2. **API keys → Create key**, name it `AdPulse`, and copy it. You only see it once.
3. In **Render → adpulse → Environment → Add Environment Variable**: key `ANTHROPIC_API_KEY`, value = the key. Click **Save, rebuild and deploy**.

Never paste the key into a chat or email. If it ever leaks, delete it in the console and make a new one.

## Good to know

- **Updates:** when you get a new version of AdPulse, upload the changed files to GitHub the same way.
  Render redeploys automatically.
- **Supabase pauses** a free project after a week with no activity. The keep-awake job in Step 5 prevents this.
- **Upgrading later:** once you have paying clients, Render's paid plan (~US$7/month) removes the sleep and
  the one-minute first load. Nothing else changes.
- **Local copy:** `start.bat` on your computer still works on its own, using a local file for its data,
  separate from the online version.
