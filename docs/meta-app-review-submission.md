# Meta App Review submission pack

App: ManyOsirisChat, Meta app `1321099496095662`.
Derived from the code on `main`. Where Meta's own wording could not be confirmed it is marked **(verify)**. Meta's pages checked while writing this: [App Review for Instagram API](https://developers.facebook.com/docs/instagram-platform/app-review) and [Permissions Reference](https://developers.facebook.com/docs/permissions) (the WhatsApp entries were past the part of the page that could be read).

## 1. Standard vs Advanced access (read this first)

- **Only your own accounts:** Instagram Login with **Standard Access** needs no App Review for a single business you own or manage. Add the Instagram accounts as app testers/roles and use the app as is.
- **Serving other businesses:** you must request **Advanced Access** per permission, which requires App Review (and Business Verification for Advanced Access in general). That is the case this pack is written for.
- Meta says an app uses Facebook Login or Instagram Login, not both. This app's Instagram connection is Instagram Login.
- Do not submit for permissions you will not use: Meta rejects requests that do not match usage. `instagram_business_content_publish` is not used by the code and must not be requested.
- For Facebook Pages and WhatsApp, Standard access likewise only covers people with a role on the app **(verify the exact rules for each in the dashboard)**.

## 2. Permissions the code actually uses

Instagram scopes are the only ones the backend itself requests: `build_oauth_url` in `backend/app/integrations/meta/oauth.py` asks for `instagram_business_basic,instagram_business_manage_messages,instagram_business_manage_comments`. Facebook Pages and WhatsApp permissions are not requested in code; they come from the Login-for-Business / Embedded Signup configurations (`FACEBOOK_LOGIN_CONFIG_ID`, `WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID`) set in the Meta dashboard, so what is actually requested there must be checked in the dashboard.

### Instagram (graph.instagram.com, Instagram Login)

| Permission | Calls in code | Webhook field |
|---|---|---|
| `instagram_business_basic` | `GET /me` (`accounts.py`, account metadata on connect), `GET /me/media` (`accounts.py`, media picker for campaigns), `GET /refresh_access_token` (`token_refresh.py`; Meta lists this permission as required) | – |
| `instagram_business_manage_messages` | `POST /{ig_user_id}/messages` with `recipient.comment_id` (private reply) and `recipient.id` (DM, follow prompt card), `GET /{IGSID}?fields=username`, `GET /{IGSID}?fields=is_user_follow_business` (`messaging.py`) | `messages`, `messaging_postbacks` |
| `instagram_business_manage_comments` | `POST /{comment-id}/replies` (public comment reply, `messaging.py`, used when a campaign has `comment_reply_enabled`) | `comments` |

### Facebook Pages (graph.facebook.com)

| Permission | Calls in code |
|---|---|
| `pages_show_list` | `GET /me/accounts` (list the Pages the person granted, `facebook_oauth.py`) |
| `pages_manage_metadata` | `POST /{page_id}/subscribed_apps` with `feed,messages,messaging_postbacks` (Meta: "Subscribe to receive webhooks of your Page") |
| `pages_messaging` | `POST /{page_id}/messages` with `recipient.comment_id` (private reply) and `recipient.id` (DM), `facebook_client.py` |
| `pages_read_engagement` | No direct Graph read in code; comments arrive through the `feed` webhook. Probably needed for that webhook **(verify against Meta's Page webhooks and Private Replies docs before requesting)** |

### WhatsApp (graph.facebook.com)

| Permission | Calls in code |
|---|---|
| `whatsapp_business_messaging` | `POST /{phone_number_id}/messages` (text and template sends, `whatsapp_client.py`) |
| `whatsapp_business_management` | `POST /{waba_id}/subscribed_apps`, `GET /{phone_number_id}?fields=display_phone_number,verified_name`, `GET`/`POST`/`DELETE /{waba_id}/message_templates`, `GET /{waba_id}/phone_numbers?fields=id,verified_name,display_phone_number,quality_rating` |

Webhook fields handled: `messages`, `message_template_status_update`, `phone_number_quality_update`; `message_template_quality_update` and `account_update` are stored only.

### Mismatches to resolve before submitting

- **Requested but not used:** `pages_manage_engagement` is listed in the comment in `backend/app/core/config.py` (next to `FACEBOOK_LOGIN_CONFIG_ID`) but no code creates, edits or deletes a Page comment or like. Remove it from the Facebook Login for Business configuration and do not request it. (The privacy page already omits it.)
- **Used but not requested by code:** nothing is missing for Instagram. All three requested scopes are used, including `instagram_business_manage_comments` for the public comment reply and the `comments` webhook. For Facebook and WhatsApp, "requested" cannot be confirmed from the repo; compare the lists above with the actual configurations.
- **Not requested, not used:** `instagram_business_content_publish`, `pages_manage_posts`, `business_management`.
- **Permission mapping unverified:** which permission covers the username and `is_user_follow_business` lookups by IGSID is assumed to be `instagram_business_manage_messages` (they only work for people who messaged the business) **(verify)**. The one thing Meta's page says about `instagram_business_manage_comments` allowed usage was ambiguous in the fetched copy **(verify the exact text in the submission form)**.

## 3. Use case and allowed-usage statements

Use this framing everywhere: ManyOsirisChat is a **customer-support and lead-follow-up assistant for a specific business**. A business connects its own Instagram Business account, Facebook Page or WhatsApp number and configures keyword-triggered replies and, optionally, replies written by AI from that business's own profile. It is **not a general-purpose AI assistant**: it only answers people who commented on that business's posts or messaged that business, and only about that business.

### `instagram_business_basic`
- **Use case:** When a business connects its Instagram professional account via Instagram Login, we read its account ID, username and account type to identify the account in our dashboard, and list its recent media so it can choose which post a campaign applies to. We also use this permission to refresh the long-lived token.
- **Allowed usage:** "Get basic metadata of an Instagram Business account profile." We read only the connected business's own profile and media.

### `instagram_business_manage_messages`
- **Use case:** A customer comments a keyword on the business's post or messages the business. We send one private reply to the comment and continue the conversation by DM within the allowed messaging window: an answer, an offer, or a link the business configured. Where the business enabled it, the reply is written by AI from the business's profile. Replies are visible in the business's native Instagram inbox.
- **Allowed usage:** "View, manage, and respond to messages" and use as a CRM-style tool to manage messages for the business. We do not message people who have not interacted with the business, and we do not broadcast.

### `instagram_business_manage_comments`
- **Use case:** When a customer comments the configured keyword, we post a public reply under that comment (for example "Check your DMs") so the customer knows a message is on its way, and we receive the comment through the `comments` webhook to trigger the private reply.
- **Allowed usage:** Manage and respond to comments on the connected business's own media. We reply only to comments on that business's posts.

### Facebook Pages
- **`pages_show_list`:** show the person the Pages they manage after Facebook Login for Business and let them pick which Pages to connect.
- **`pages_manage_metadata`:** subscribe our app to the connected Page's webhooks (`feed`, `messages`, `messaging_postbacks`) so comments and messages reach the business's automation.
- **`pages_messaging`:** send the Page's customer-support replies: a private reply to a comment and follow-up Messenger messages, in response to a person who interacted with the Page.
- **`pages_read_engagement`:** read the comment that triggered a campaign on the Page's own posts **(verify need)**.

### WhatsApp
- **`whatsapp_business_messaging`:** send replies to customers who messaged the business's number, and approved template messages to customers who opted in.
- **`whatsapp_business_management`:** subscribe to the business account's webhooks, read phone-number health and quality, and create and sync the business's message templates.
- Wording of Meta's allowed-usage text for the two WhatsApp permissions was not retrievable **(verify in the submission form)**.

## 4. Screencast scripts

Record at 1080p in English, with captions on every step. Show the browser address bar. **Never show an access token**: redact the `access_token` in the cURL commands and the terminal. Meta asks for a recording, not screenshots, and for each permission a screencast of the end-to-end experience.

Prerequisites for every recording: `META_MOCK_PRIVATE_REPLIES=false` on the server. With it on, `messaging.py` returns a fake success without calling Meta, so no API call is registered and nothing arrives in the Instagram inbox. Do not use the dashboard's "mock connect" button in any recording.

### 4.1 Instagram: `instagram_business_basic`
1. Open `https://manyosirischat.theosirislabs.com/login` and sign in with the test dashboard user.
2. Go to **Accounts**. Show that no Instagram account is connected (or disconnect it first).
3. Click **Connect Instagram**. Show the Instagram authorization screen listing all three permissions and tap **Allow**.
4. Back on **Accounts** the account appears, showing username and ID retrieved through `instagram_business_basic`.
5. Open **Campaigns → New campaign** and show the media picker listing the account's recent posts.

### 4.2 Instagram: `instagram_business_manage_messages`
1. Start from the connected account on **Accounts** (repeat steps 1–4 above in the same recording if it has to stand alone).
2. In **Campaigns** create a campaign with keyword `INFO` and a DM message; activate it.
3. From a second Instagram account (the tester), comment `INFO` on the connected account's post. Show the comment on the phone.
4. In the dashboard show **Logs** and **Messages**: the webhook arrived and the private reply was delivered.
5. On the phone open the Instagram app inbox of the tester: the message from the business is visible. Reply to it; show the reply arriving in **Conversations**.
6. In a terminal, send a DM with cURL and show the message arriving in the native inbox (token redacted):
   ```bash
   curl -X POST "https://graph.instagram.com/v21.0/<IG_USER_ID>/messages?access_token=<REDACTED>" \
     -H "Content-Type: application/json" \
     -d '{"recipient":{"id":"<IGSID_OF_TESTER>"},"message":{"text":"Hello from the review test"}}'
   ```
   The recipient must have messaged the business within the last 24 hours. The code sends the token as the `access_token` query parameter, as above.

### 4.3 Instagram: `instagram_business_manage_comments`
1. Edit the campaign and tick **Reply publicly to the comment** (labelled "Public comment reply" in places) with the text "Check your DMs".
2. From the tester account comment `INFO` on the post.
3. Show the dashboard **Logs** entry `comment_reply_sent`, then the public reply under the comment in the native Instagram app, from the business account.

### 4.4 Facebook Pages
1. **Accounts → Connect Facebook Page**. Show the Facebook Login for Business dialog with the permissions and the Page picker (`pages_show_list`); select the Page.
2. Show the Page appearing connected (webhook subscription done, `pages_manage_metadata`).
3. Create a Facebook campaign with a keyword; comment it on a Page post from a tester profile; show the private reply arriving in Messenger and the Page inbox, and a follow-up message (`pages_messaging`). Add the cURL for `POST /{page_id}/messages`.

### 4.5 WhatsApp
1. **WhatsApp → Connect WhatsApp** and run Embedded Signup with a test number; show the consent screen.
2. Show the account health/quality and template sync (`whatsapp_business_management`).
3. From a test phone message the number; show the reply arriving in WhatsApp and the thread in **Conversations** (`whatsapp_business_messaging`); show an approved template send to an opted-in contact.

## 5. Reviewer test instructions

Paste into the submission form and fill the placeholders; do not put real secrets in this repository.

1. Dashboard: `https://manyosirischat.theosirislabs.com/login`, user `<reviewer email>`, password `<reviewer password>`. Create a dedicated reviewer user with a role that can manage accounts and campaigns.
2. Instagram: connect the test business account `<@test_business>` with **Connect Instagram** (log in with `<test business login>`). Add the reviewer as a tester on the app and the Instagram account as an Instagram Tester.
3. Create a campaign with keyword `INFO`, activate it, then comment `INFO` on the post `<link>` from `<@test_customer>` (credentials `<…>`). Expect a public reply and a DM within a few seconds.
4. For messaging, DM the business from `<@test_customer>`; reply in the app and the customer receives it.
5. Facebook: Page `<test page>`; WhatsApp: test number `<+…>` with a second phone for inbound messages.

Test material to provide: the dashboard user, an Instagram professional test business account, a second Instagram account to act as the customer, a Facebook test Page and profile, and a WhatsApp test number. Keep every account free of real customer data and 2FA-free or with a reviewer-accessible method.

## 6. Dashboard settings checklist (owner, Meta app `1321099496095662`)

- [ ] **Data Deletion Instructions URL:** `https://manyosirischat.theosirislabs.com/privacy#data-deletion` (currently not set).
- [ ] **Privacy Policy URL:** `https://manyosirischat.theosirislabs.com/privacy`. **Terms of Service URL:** `https://manyosirischat.theosirislabs.com/terms`.
- [ ] **Verified contact email** (`privacy@theosirislabs.com` is the one on the policy; the business email must be a monitored address) and **business email** in Settings → Basic.
- [ ] **Support / User Data / Help URL** and an **app description** matching section 3 (a customer-support assistant for specific businesses).
- [ ] **App icon 1024×1024** and an app category.
- [ ] **Instagram Login:** valid OAuth redirect URI `{APP_BASE_URL}/meta/connect/callback`; webhook callback `{APP_BASE_URL}/webhooks/meta` with `META_WEBHOOK_VERIFY_TOKEN`; subscribe `comments`, `messages`, `messaging_postbacks`.
- [ ] **Facebook Login for Business config:** only the permissions in section 2 (remove `pages_manage_engagement`); webhook fields `feed`, `messages`, `messaging_postbacks`.
- [ ] **WhatsApp:** Embedded Signup config id set; webhook fields `messages`, `message_template_status_update`, `phone_number_quality_update`.
- [ ] **API pre-check:** at least one successful API call per permission before requesting Advanced Access (Meta: "make at least one successful API call"). Run the flows in section 4 with `META_MOCK_PRIVATE_REPLIES=false` first and confirm each call in the dashboard's API activity.
- [ ] **Business Verification** (needed for Advanced Access) and, if serving other businesses, Tech Provider steps.
- [ ] The login button/link is visible in the app and in the screencast and follows Meta's brand guidelines.
- [ ] Do not request `instagram_business_content_publish`, `pages_manage_engagement` or any permission not in section 2.
