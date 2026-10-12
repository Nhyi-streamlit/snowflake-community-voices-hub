# Community Voices — onboarding and go-live kit (speakers and event organizers)

App: https://nhyi-streamlit-snowflake-community-voices--streamlit-app-an16ay.streamlit.app

| Audience | Start here |
|---|---|
| Everyone | `/` (Homepage): "I'm a speaker" / "I'm organizing an event" |
| Speakers | `/Speaker_Portal` (sections: Get started, Speak at an event, Resources, Travel & expenses, After your talk) |
| Event organizers | `/Vendor_Portal` |
| Instructions | `/help` (`?topic=speakers`, `organizers`, `signin`, `bulk`, `travel`, `contact`) |
| Audience feedback | `/Speaker_Portal?speaker=…&event=…&talk=…` (no sign-in) |

All user-facing instructions live on the Help page. Portals link to it instead of repeating text.

## 1. Make the app reachable (Community Cloud)

1. Open share.streamlit.io → the app's **⋮ → Settings → Sharing**.
2. Set **Who can view this app** to **This app is public and searchable** (or public, unlisted).
3. Program-team pages (Workflow admin, Admin Portal, Navan) are **not listed** in the public sidebar. They appear
   only for allowlisted Google admins or after the program-team password is entered via **Program team sign-in**
   (sidebar). Their direct URLs still work and show the password form.

## 2. Sign-in: emailed one-time codes (speakers and organizers)

The company Google OAuth project is Internal-only, so external users sign in with a **6-digit code emailed to them**.
Speakers use the same sign-in for personal sections (reimbursement, event headcount).

- **Sender:** codes go through the Gmail API with `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` /
  `GOOGLE_REFRESH_TOKEN`. Recipients see **the mailbox that refresh token belongs to** as the sender. A shared
  program mailbox is strongly recommended. The token needs the `gmail.send` scope.
- **Gmail API must be enabled** in the OAuth client's Google Cloud project (project `25733770608`). If it isn't,
  every send fails with `SERVICE_DISABLED`.
- **Security:** codes expire after 10 minutes, allow 5 attempts, and work once. Only an HMAC is kept in server memory.
  Limits: 3 codes per email per 15 min, 10 per day, 5 per browser session, 200 per hour app-wide.
- **Sessions:** 12 hours. A browser refresh or new tab needs a new code. An app restart clears pending codes.
- **Optional secrets:** `OTP_SECRET = "<random string>"` keeps code hashing stable across processes.
  `GMAIL_SENDER = "program@…"` is shown on Email health when the token can't read the mailbox address.
- Email-code users are **never admins**. The admin allowlist only matches Google sign-ins.

### Diagnosing email failures
Open **Workflow admin → Email health** (admins only). It shows:
- the sender address
- whether the Gmail API is reachable
- the last send result, with Google's reason code and a suggested fix
- **Send test code to me**, which sends only to the signed-in admin's own address

Common reasons:

| Reason | Fix |
|---|---|
| `SERVICE_DISABLED` | Enable the Gmail API in the GCP project, wait a few minutes, send a test code |
| `ACCESS_TOKEN_SCOPE_INSUFFICIENT` / `insufficientPermissions` | Re-authorize the mailbox with `gmail.send`, update `GOOGLE_REFRESH_TOKEN` |
| `invalid_grant` | Refresh token revoked/expired: re-authorize and update the secret |
| `invalid_client` | Client ID/secret wrong |
| `missing_credentials` | A `GOOGLE_*` secret is missing |
| `network_error` | Temporary; retry |

App logs record `reason` and HTTP status only. They never record tokens, codes, email bodies, or full addresses.

### Optional: Google sign-in (`st.login`)
Only useful once IT provides an **External** OAuth project. If so, add `[auth]` and a secondary
"Sign in with Google" button appears. Admins still need Google sign-in (allowlist `ADMIN_GOOGLE_SUBJECTS`) to use the
Email health test button, because password-only sessions have no email address.

```toml
[auth]
redirect_uri = "https://nhyi-streamlit-snowflake-community-voices--streamlit-app-an16ay.streamlit.app/oauth2callback"
cookie_secret = "<random 32+ characters>"
client_id = "<OAuth client ID>.apps.googleusercontent.com"
client_secret = "<OAuth client secret>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```
Don't commit any of these values.

### Which backend organizers use
- If `[connections.cv_workflow]` is **not** set, submissions append to the **Events** and **Speaker_Requests** sheet
  tabs and show in the **Admin Portal**.
- If it **is** set, submissions go through the workflow service and show in **Workflow admin**.
- The Homepage and Speaker Portal list only **Approved** events from the Events tab (name, city, country, dates,
  format).

## 3. What speakers can do today
- **Open to everyone:** upcoming events, Brand Kit, Talk Templates, Speaker Prep, the talk feedback QR generator, and
  the audience rating form.
- **Email-code sign-in:** reimbursement (with receipt upload where enabled) and event headcount (YOLOX detector;
  photos are not stored).
- **Paused (shown as one "Coming soon" card):** speaking-slot signup, travel booking, and Uber codes.

## 4. Draft invite email (NOT sent — review first)

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

## 5. Combined test script

Use a private/incognito window and two email addresses you're allowed to use (A and B).

0. **Email health (after enabling the Gmail API):** Sign in with Google as an admin → Workflow admin → Email
   health → **Check now**. Expect "Reachable". Click **Send test code to me** and expect the email within a minute.
   If it fails, the panel names the Google reason and the fix.
1. **Homepage, signed out:** You see the hero, two CTAs, How it works, upcoming events, and FAQ. The sidebar shows
   Homepage, Speaker Portal, Vendor Portal, Help, and "Program team sign-in", but **no** admin pages. Each CTA opens
   the right portal.
2. **Speaker Portal, signed out:** All five sections render without errors. *Travel & expenses* shows one "Coming
   soon" card and a sign-in box for reimbursement. *After your talk* shows the QR generator and a sign-in box for
   headcount.
3. **Feedback QR:** Generate a QR code, open its link in a new private window, submit a rating with no sign-in, and
   confirm a row appears in `Talk_Feedback`.
4. **Speaker sign-in:** In *After your talk*, sign in with A (wrong code once, expect "4 attempt(s) left"). Upload a
   room photo, adjust the count, and save. Confirm a row appears in `Event_Headcount`.
5. **Organizer flow:** In the Vendor Portal, sign in with A. Register an event (try an end date before the start date
   and a CFP deadline after the start date, expect inline errors), go Back once (answers persist), then Submit and
   expect a reference ID.
6. **Bulk:** Download the template from Help → Bulk upload template. Upload 3 rows, one a duplicate of step 5, and
   expect the duplicate skipped. Upload a bad URL and expect the error table to name the row and column.
7. **Scoping:** Sign out, sign in with B, and confirm **My events** is empty. As admin, confirm the events appear in
   the Admin Portal (Sheets mode) or Workflow admin.
8. **Help:** Open `/help?topic=signin` and confirm it opens on Signing in. Every "Help" link in the portals opens
   the matching topic.
