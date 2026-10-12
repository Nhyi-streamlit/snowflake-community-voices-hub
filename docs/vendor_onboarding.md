# Vendor Portal — go-live and onboarding kit

Public URL: https://nhyi-streamlit-snowflake-community-voices--streamlit-app-an16ay.streamlit.app/Vendor_Portal

## 1. Make the app reachable (Community Cloud)

1. Open share.streamlit.io → the app's **⋮ → Settings → Sharing**.
2. Set **Who can view this app** to **This app is public and searchable** (or public, unlisted).
   Without this, vendors are sent to a Streamlit login wall before they ever reach the portal.
   Program-team pages stay protected by their own password / admin allowlist checks.

## 2. Google sign-in (`st.login`)

### Google Cloud console
1. APIs & Services → **OAuth consent screen**:
   - User type: **External**
   - Scopes: `openid`, `email`, `profile` (nothing else)
   - **Publishing status: In production.** In "Testing", only listed test users can sign in — new vendors will be blocked.
     These three scopes are non-sensitive, so publishing does not require Google verification.
2. Credentials → **Create OAuth client ID** → *Web application*:
   - Authorized redirect URI (exact):
     `https://nhyi-streamlit-snowflake-community-voices--streamlit-app-an16ay.streamlit.app/oauth2callback`
   - Add `http://localhost:8501/oauth2callback` too if you test locally.

### App secrets (Community Cloud → Settings → Secrets)
```toml
[auth]
redirect_uri = "https://nhyi-streamlit-snowflake-community-voices--streamlit-app-an16ay.streamlit.app/oauth2callback"
cookie_secret = "<random 32+ characters, e.g. output of: python -c 'import secrets;print(secrets.token_urlsafe(48))'>"
client_id = "<OAuth client ID>.apps.googleusercontent.com"
client_secret = "<OAuth client secret>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```
Keep the existing Google Sheets secrets (`GOOGLE_*`). Don't commit any of these values.

### Which backend vendors use
- If `[connections.cv_workflow]` is **not** set: submissions append to the **Events** and **Speaker_Requests**
  Google Sheet tabs and show in the **Admin Portal** (Vendor Events).
- If it **is** set: submissions go through the workflow service and show in **Workflow admin** (proposed events).
- Signed-in admins see a banner on the Vendor Portal saying which mode is active.
- Workflow mode allows at most 5 pending proposals per vendor at a time.

## 3. Draft invite email (NOT sent — review first)

**Subject:** Request a Snowflake community speaker for your event

> Hi {first name},
>
> If you're organizing a conference, meetup, or university event and would like a speaker from the Snowflake
> community — Data Superheroes, Streamlit Creators, and community experts — you can now register it in a few minutes:
>
> **{Vendor Portal link}**
>
> 1. Click **Sign in with Google** (any Google account works, including Gmail).
> 2. Tell us about your event and the topic you'd like covered. Have several events? Upload them all with our spreadsheet template.
> 3. You'll get a reference ID right away. We review every event within 5 business days and will be in touch about speaker matches.
>
> You can check status and edit pending events anytime under **My events**.
>
> Questions? Just reply to this email or write to community@snowflake.com.
>
> Thanks,
> Aba Micah
> Community Voices, Snowflake

## 4. Fake-vendor test script (personal Gmail)

Use a private/incognito window and a Gmail account that has never used the app.

1. **Access** — Open the public URL. Expect: the landing page with "How it works", the FAQ, and **Sign in with Google**.
   You should *not* see a Streamlit login page or an error.
2. **Sign in** — Click Sign in with Google and pick the Gmail account. Expect to land back on the Vendor Portal
   with "Signed in as you@gmail.com".
3. **Single event** — Register an event: on Step 2 try an end date before the start date, and on Step 3 a CFP
   deadline after the start date (expect inline errors). Fix them, go Back once (answers should persist), then
   Submit. Expect a reference ID with a copy button and the "What happens next" timeline.
4. **Bulk** — Bulk upload → Download template → replace the example with 3 events (make one a copy of the event
   from step 3) → upload. Expect the duplicate to be skipped and 2 submitted; then upload a file with a bad URL and
   confirm the error table names the row and column.
5. **Verify** — Open **My events**: all events show as *Pending*, and Edit works on one. Sign out, sign in as a
   different Gmail: My events must be empty. Finally, as admin, confirm the events appear in the Admin Portal
   (Sheets mode) or Workflow admin (workflow mode).
