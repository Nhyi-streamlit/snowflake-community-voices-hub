# Vendor Portal — go-live and onboarding kit

Public URL: https://nhyi-streamlit-snowflake-community-voices--streamlit-app-an16ay.streamlit.app/Vendor_Portal

## 1. Make the app reachable (Community Cloud)

1. Open share.streamlit.io → the app's **⋮ → Settings → Sharing**.
2. Set **Who can view this app** to **This app is public and searchable** (or public, unlisted).
   Without this, vendors are sent to a Streamlit login wall before they ever reach the portal.
   Program-team pages stay protected by their own password / admin allowlist checks.

## 2. Vendor sign-in: emailed one-time codes (default)

The company Google OAuth project is Internal-only, so vendors sign in with a **6-digit code emailed to them**.
No Google Cloud setup and no new secrets are required.

- **Sender:** codes are sent through the Gmail API with the existing `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` /
  `GOOGLE_REFRESH_TOKEN`. Vendors see **the mailbox that refresh token belongs to** as the sender. A shared program
  mailbox is strongly recommended over a personal inbox. The token must include the `gmail.send` scope (it already
  does if receipt/notification emails work).
- **Security:** codes expire after 10 minutes, allow 5 attempts, and work once. Only an HMAC of the code is kept, in
  server memory. Limits: 3 codes per email per 15 min, 10 per day, 5 per browser session, 200 per hour app-wide.
- **Sessions:** a verified session lasts 12 hours. A browser refresh or a new tab needs a new code (Streamlit can't
  set cookies). An app restart clears pending codes.
- **Optional secret:** `OTP_SECRET = "<random string>"` keeps code hashing stable across processes. It isn't needed
  on a single Community Cloud instance.
- Email-code users are **never admins**; the admin allowlist only matches Google sign-ins.

### Optional: Google sign-in (`st.login`)
Only useful once IT provides an **External** OAuth project. Snowflake's org policy blocks External consent screens,
and personal projects aren't allowed. If that happens, add the block below and a secondary "Sign in with Google"
button appears.

Redirect URI: `https://nhyi-streamlit-snowflake-community-voices--streamlit-app-an16ay.streamlit.app/oauth2callback`

### App secrets for optional Google sign-in (Community Cloud → Settings → Secrets)
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
> 1. Enter your email and click **Email me a code**, then type the 6-digit code we send you. No password or account needed.
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

## 4. Test script (two email addresses you're allowed to use)

Use a private/incognito window. Your snowflake.com address works for the flow. For the scoping check, use a second
address you're permitted to access, such as a shared program mailbox or a colleague who agrees to help.

1. **Access** — Open the public URL signed out. Expect the landing page with "How it works", the FAQ, and the
   **Sign in with your email** box. You should *not* see a Streamlit login page or an error.
2. **Sign in** — Enter address A → **Email me a code**. The code should arrive within a minute (check spam).
   Enter a wrong code once (expect "4 attempt(s) left"), then the right one. Expect "Signed in as A".
3. **Single event** — Register an event: on Step 2 try an end date before the start date, and on Step 3 a CFP
   deadline after the start date (expect inline errors). Fix them, go Back once (answers should persist), then
   Submit. Expect a reference ID with a copy button and the "What happens next" timeline.
4. **Bulk** — Bulk upload → Download template → replace the example with 3 events (make one a copy of the event
   from step 3) → upload. Expect the duplicate to be skipped and 2 submitted; then upload a file with a bad URL and
   confirm the error table names the row and column.
5. **Verify** — Open **My events**: all events show as *Pending*, and Edit works on one. Sign out, sign in with
   address B: My events must be empty. Finally, as admin, confirm the events appear in the Admin Portal
   (Sheets mode) or Workflow admin (workflow mode).
