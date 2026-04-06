# Z-Pay — Setup & Operations Guide

## READ THIS FIRST — For Claude

You are helping set up and run Z-Pay, a payroll system for a transportation company. The person you're helping is not technical. She will not know if something goes wrong unless you tell her clearly. Be patient, be specific, and confirm every step worked before moving to the next.

This briefing tells you everything you need to know. Read it fully before doing anything.

---

## The Safety Rule — Most Important Thing

This computer may already have Z-Pay folders or payroll files on it from previous work. **You must not touch, modify, or go near any existing folders.** They are the safety net — if anything goes wrong with the new setup, she can go back to what was working before. That fallback only exists if you leave the existing files completely untouched.

Before doing anything, run these commands and look at the output:
```
ls ~/Documents
ls ~/Desktop
ls ~
```

Note any folders related to z-pay, zpay, payroll, or anything similar. **Do not enter them. Do not modify them.** Just know where they are so you stay away.

---

## What Z-Pay Is

Z-Pay is a payroll and business dashboard for a transportation company. Drivers take rides from two partners:
- **Acumen** (also called FirstAlt) — sends ride data as Excel files
- **Maz** (also called EverDriven) — sends ride data as PDF files

Z-Pay imports those files, calculates how much each driver earned, and sends them their pay stubs. That's the core job.

---

## Step 1 — Get the Files Ready

Malik should have sent you two things:
1. A link to the GitHub repository
2. A file called `.env` (attached to the email or sent separately)

**Do not proceed without both.** The `.env` file contains passwords the app needs to connect to its database and send emails. Without it, nothing works.

If the `.env` file is missing, stop and have her contact Malik.

---

## Step 2 — Check Docker Is Running

Docker Desktop should already be installed. Confirm it's running:
```
docker info
```

If you see an error like "Cannot connect to the Docker daemon," Docker Desktop isn't open. Have her find the Docker Desktop app (it has a whale icon in the menu bar at the top of the screen). Open it and wait until the icon stops animating. Then try again.

---

## Step 3 — Clone Into a New Folder

Clone the GitHub repository into a brand new folder called `z-pay-new`. Replace `[REPO_URL]` with the link from Malik's email:
```
git clone [REPO_URL] ~/Documents/z-pay-new
```

This creates a fresh, separate folder. All your work stays inside `~/Documents/z-pay-new`. Never go outside of it.

---

## Step 4 — Add the .env File

Copy the `.env` file Malik sent into the new folder:
```
cp ~/Downloads/.env ~/Documents/z-pay-new/.env
```

If the file is somewhere else (desktop, etc.), adjust the path. Then confirm it's there:
```
ls -la ~/Documents/z-pay-new/.env
```

You should see the file listed. If not, stop and find out where the `.env` file landed.

---

## Step 5 — Start Z-Pay

```
cd ~/Documents/z-pay-new
docker compose up -d
```

The first time this runs it will take several minutes — it's downloading and building everything. Tell her this upfront so she doesn't think it's frozen.

When it's ready you'll see:
```
Uvicorn running on http://0.0.0.0:8000
```

Then open a browser and go to: **http://localhost:8000**

The dashboard should appear with a sidebar showing pages like Payroll, Upload, People, etc.

---

## How to Use Z-Pay Day to Day

### Starting the app (every session)
Open Terminal, then:
```
cd ~/Documents/z-pay-new
docker compose up -d
```
Wait 15–20 seconds, then go to **http://localhost:8000** in the browser.

### Stopping the app when done
```
docker compose down
```

---

## The Payroll Cycle

### 1. Upload ride data
- Go to **Upload** in the sidebar
- Acumen/FirstAlt files are **Excel (.xlsx)** — upload under Acumen
- Maz/EverDriven files are **PDF** — upload under Maz
- **Never mix them** — they are separate companies that must stay separate

### 2. Run payroll
- Go to **Payroll** in the sidebar
- Select the batch (the rides just uploaded)
- Review the numbers before doing anything else

### 3. Send pay stubs
- From the Payroll page, send emails directly to drivers or export as PDF/Excel
- Drivers who earned under $100 automatically carry forward to the next batch — the system handles this

### 4. Review history
- Go to **Payroll History** to see any past payroll run

---

## Pages She'll Use Most

| Page | What it does |
|---|---|
| **Upload** | Import new ride files from Acumen or Maz |
| **Payroll** | Calculate and send payroll for a batch |
| **Payroll History** | View all past payroll runs |
| **People** | Driver directory |
| **Alerts** | Anything flagged that needs attention |

The other pages (Dispatch, Intelligence, Validation) are for advanced use — she likely won't need them day to day.

---

## If Something Goes Wrong

**App won't start:**
```
cd ~/Documents/z-pay-new
docker compose logs app --tail=30
```
Read the output and figure out what it says.

**Page won't load:**
```
docker compose ps
```
Both `db` and `app` should say "Up". If not, try:
```
docker compose down
docker compose up -d
```

**Numbers look wrong:** Stop. Do not proceed. Have her contact Malik directly.

**Anything feels risky or unclear:** Stop. The original setup is still untouched. She can go back to it at any time. Protecting that option matters more than pushing forward.

---

## The Golden Rule

The existing folders on this computer are her safety net. As long as you never touch them, she can always go back to the way things were. Protect that option above everything else.

---

## About This System

Z-Pay was built by Malik for his transportation company. It handles payroll, driver management, dispatch, and business analytics. The rates each driver earns are already loaded into the database — nothing needs to be configured from scratch. The app just needs to be running and the ride files uploaded each pay period.

If Malik needs to be reached for anything that can't be resolved here, stop and have her call or text him rather than guessing.
