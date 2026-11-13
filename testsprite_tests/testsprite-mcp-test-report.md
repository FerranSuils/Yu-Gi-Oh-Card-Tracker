# TestSprite AI Testing Report(MCP)

---

## 1️⃣ Document Metadata
- **Project Name:** Yu-Gi-Oh-Card-Tracker (OpenYuGi)
- **Date:** 2026-11-09
- **Prepared by:** TestSprite AI Team
- **Target:** local instance of the `features/mostrador-ui-973a` branch with the uncommitted fixes, http://localhost:8206
- **Runs:** run 1 had all 20 cases. Run 2 re-ran the 4 cases that did not pass, after fixing the login button. Run 1 raw output is kept in `tmp/raw_report_run1.md`.

---

## 2️⃣ Requirement Validation Summary

### Requirement: Signup
- **Description:** Anyone can create a free account from /registro, and the new account lands signed in on its own empty collection.

#### Test TC001 Create an account and arrive in an empty private collection
- **Test Code:** [TC001](./TC001_Create_an_account_and_arrive_in_an_empty_private_collection.py)
- **Test Visualization and Result:** https://www.testsprite.com/dashboard-v3/o/c09da5e8-63e9-5b6d-b467-be07561cc23c/projects/mcp/3c08f3f2-2601-59f0-aee7-c3f3391a7ce8/test/6be29f93-cfcb-4de5-a46e-d26c191c23c5
- **Status:** ✅ Passed
- **Severity:** LOW
- **Analysis / Findings:** Signup reaches /collection signed in. This is the flow that was broken in production by the IIS WebSocket handshake.
---

#### Test TC004 New account signup lands in an empty private collection
- **Test Code:** [TC004](./TC004_New_account_signup_lands_in_an_empty_private_collection.py)
- **Test Visualization and Result:** https://www.testsprite.com/dashboard-v3/o/c09da5e8-63e9-5b6d-b467-be07561cc23c/projects/mcp/3c08f3f2-2601-59f0-aee7-c3f3391a7ce8/test/d3354f6e-3fca-4000-a4f5-bbdc1ca6b4c5
- **Status:** ✅ Passed
- **Severity:** LOW
- **Analysis / Findings:** The new account sees an empty collection.
---

#### Test TC012 Second account sees a separate empty private collection
- **Test Code:** [TC012](./TC012_Second_account_sees_a_separate_empty_private_collection.py)
- **Test Visualization and Result:** https://www.testsprite.com/dashboard-v3/o/c09da5e8-63e9-5b6d-b467-be07561cc23c/projects/mcp/3c08f3f2-2601-59f0-aee7-c3f3391a7ce8/test/37a8f378-9b2c-48bd-b054-2de3000eaba3
- **Status:** ✅ Passed
- **Severity:** LOW
- **Analysis / Findings:** Collections are isolated per account.
---

#### Test TC014 Create a second account and see a separate empty collection
- **Test Code:** [TC014](./TC014_Create_a_second_account_and_see_a_separate_empty_collection.py)
- **Test Visualization and Result:** https://www.testsprite.com/dashboard-v3/o/c09da5e8-63e9-5b6d-b467-be07561cc23c/projects/mcp/3c08f3f2-2601-59f0-aee7-c3f3391a7ce8/test/d8e4321d-1369-4e5e-9941-117b9e2bf9e6
- **Status:** ✅ Passed
- **Severity:** LOW
- **Analysis / Findings:** Same as TC012, reached through a separate path.
---

### Requirement: Signup validation
- **Description:** The form rejects an invalid username, a short password, mismatched passwords and an existing username, and shows the error inline.

#### Test TC016 Reject an invalid username during registration
- **Test Code:** [TC016](./TC016_Reject_an_invalid_username_during_registration.py)
- **Test Visualization and Result:** https://www.testsprite.com/dashboard-v3/o/c09da5e8-63e9-5b6d-b467-be07561cc23c/projects/mcp/3c08f3f2-2601-59f0-aee7-c3f3391a7ce8/test/5f10a920-a612-4459-8965-5875fe6a1f1e
- **Status:** ✅ Passed
- **Severity:** LOW
- **Analysis / Findings:** The form shows the inline error.
---

#### Test TC017 Reject a short password during registration
- **Test Code:** [TC017](./TC017_Reject_a_short_password_during_registration.py)
- **Test Visualization and Result:** https://www.testsprite.com/dashboard-v3/o/c09da5e8-63e9-5b6d-b467-be07561cc23c/projects/mcp/3c08f3f2-2601-59f0-aee7-c3f3391a7ce8/test/b1f9c631-66de-4003-806d-efb116aeb3f9
- **Status:** ✅ Passed
- **Severity:** LOW
- **Analysis / Findings:** The form shows the inline error.
---

#### Test TC018 Reject mismatched password confirmation during registration
- **Test Code:** [TC018](./TC018_Reject_mismatched_password_confirmation_during_registration.py)
- **Test Visualization and Result:** https://www.testsprite.com/dashboard-v3/o/c09da5e8-63e9-5b6d-b467-be07561cc23c/projects/mcp/3c08f3f2-2601-59f0-aee7-c3f3391a7ce8/test/b82b5ce5-b415-49d7-ac02-5a1975d0777b
- **Status:** ✅ Passed
- **Severity:** LOW
- **Analysis / Findings:** "Las contraseñas no coinciden." is shown and no request is sent.
---

#### Test TC019 Reject an existing username during registration
- **Test Code:** [TC019](./TC019_Reject_an_existing_username_during_registration.py)
- **Test Visualization and Result:** https://www.testsprite.com/dashboard-v3/o/c09da5e8-63e9-5b6d-b467-be07561cc23c/projects/mcp/3c08f3f2-2601-59f0-aee7-c3f3391a7ce8/test/bf929ece-f5c0-494a-aece-79ab9e3d9c35
- **Status:** ✅ Passed
- **Severity:** LOW
- **Analysis / Findings:** The duplicate is rejected with an inline error.
---

### Requirement: Login and session
- **Description:** An existing account signs in with "Entrar al mostrador" and stays signed in across navigation and reloads.

#### Test TC005 Registered user stays signed in after returning to the collection
- **Test Code:** [TC005](./TC005_Registered_user_stays_signed_in_after_returning_to_the_collection.py)
- **Test Visualization and Result:** https://www.testsprite.com/dashboard-v3/o/c09da5e8-63e9-5b6d-b467-be07561cc23c/projects/mcp/3c08f3f2-2601-59f0-aee7-c3f3391a7ce8/test/012e5c7c-fd9b-445c-bed6-75e0db90d0d4
- **Status:** ✅ Passed (run 2). It was BLOCKED in run 1.
- **Severity:** HIGH (run 1), fixed
- **Analysis / Findings:** Run 1 found a real bug. The login button reused the signup JavaScript handler, so it sent a POST to /api/v1/register. That request got a 400 because the user already existed, no error was shown, and the page stayed on /login. This was reproduced in production too. The fix gives login its own handler (`_LOGIN_FIELDS_JS`, which sends the typed values to the Python handler). A regression test was added in `tests/test_login_handler.py`.
---

#### Test TC010 Sign in and keep access after revisiting the collection page
- **Test Code:** [TC010](./TC010_Sign_in_and_keep_access_after_revisiting_the_collection_page.py)
- **Test Error:** Run 2: "Usuario o contraseña incorrectos." was shown and the page stayed on /login.
- **Test Visualization and Result:** https://www.testsprite.com/dashboard-v3/o/c09da5e8-63e9-5b6d-b467-be07561cc23c/projects/mcp/3c08f3f2-2601-59f0-aee7-c3f3391a7ce8/test/035b0353-ce0b-4ad3-b7a0-796cee33f8c7
- **Status:** ❌ Failed. Run 1 was caused by the login bug; run 2 did not reproduce.
- **Severity:** LOW
- **Analysis / Findings:**
  - TC005 and TC011 used the same credentials and passed in the same run.
  - The exact steps (fill username, fill password, click once) passed 10 of 10 locally with Playwright, and also passed in production.
  - The exported test also expects /collection after login. Login without `next` lands on `/`, so that assertion is wrong in the test itself.
  - Likely cause: the remote browser filled the inputs before the NiceGUI page finished connecting through the tunnel.
  - Worth watching: if real users report a wrong-password error on their first try, wait for the page to connect before enabling the button.
---

#### Test TC011 Keep the signed-in session after reloading the collection page
- **Test Code:** [TC011](./TC011_Keep_the_signed_in_session_after_reloading_the_collection_page.py)
- **Test Visualization and Result:** https://www.testsprite.com/dashboard-v3/o/c09da5e8-63e9-5b6d-b467-be07561cc23c/projects/mcp/3c08f3f2-2601-59f0-aee7-c3f3391a7ce8/test/ea0bca17-cf17-4ec1-afad-7b1ae94e0c33
- **Status:** ✅ Passed (run 2). It was BLOCKED in run 1 by the same login bug.
- **Severity:** LOW
- **Analysis / Findings:** The session survives a reload of /collection.
---

#### Test TC020 Reject incorrect login credentials
- **Test Code:** [TC020](./TC020_Reject_incorrect_login_credentials.py)
- **Test Visualization and Result:** https://www.testsprite.com/dashboard-v3/o/c09da5e8-63e9-5b6d-b467-be07561cc23c/projects/mcp/3c08f3f2-2601-59f0-aee7-c3f3391a7ce8/test/f33be9c2-c5a1-4d66-8758-cb10b6c76d6e
- **Status:** ✅ Passed
- **Severity:** LOW
- **Analysis / Findings:** "Usuario o contraseña incorrectos." is shown. In run 1 this passed for the wrong reason: the page stayed on /login because of the bug.
---

### Requirement: Route protection
- **Description:** Protected pages redirect a signed-out visitor to /login.

#### Test TC002 Open the collection page while signed out and reach the login screen
- **Test Code:** [TC002](./TC002_Open_the_collection_page_while_signed_out_and_reach_the_login_screen.py)
- **Test Visualization and Result:** https://www.testsprite.com/dashboard-v3/o/c09da5e8-63e9-5b6d-b467-be07561cc23c/projects/mcp/3c08f3f2-2601-59f0-aee7-c3f3391a7ce8/test/e017b783-8a59-4443-81f1-4ffaa3ab6a0d
- **Status:** ✅ Passed
- **Severity:** LOW
- **Analysis / Findings:** Redirects to /login.
---

#### Test TC003 Open the dashboard while signed out and reach the login screen
- **Test Code:** [TC003](./TC003_Open_the_dashboard_while_signed_out_and_reach_the_login_screen.py)
- **Test Visualization and Result:** https://www.testsprite.com/dashboard-v3/o/c09da5e8-63e9-5b6d-b467-be07561cc23c/projects/mcp/3c08f3f2-2601-59f0-aee7-c3f3391a7ce8/test/6360d42a-f14a-4dbc-8ebf-3ccfaab6a4fb
- **Status:** ✅ Passed
- **Severity:** LOW
- **Analysis / Findings:** Redirects to /login.
---

#### Test TC006 Open the deck builder while signed out and reach the login screen
- **Test Code:** [TC006](./TC006_Open_the_deck_builder_while_signed_out_and_reach_the_login_screen.py)
- **Test Visualization and Result:** https://www.testsprite.com/dashboard-v3/o/c09da5e8-63e9-5b6d-b467-be07561cc23c/projects/mcp/3c08f3f2-2601-59f0-aee7-c3f3391a7ce8/test/9bd8937a-bf6e-49ef-95f6-a2a261ebb407
- **Status:** ✅ Passed
- **Severity:** LOW
- **Analysis / Findings:** Redirects to /login.
---

#### Test TC007 Signed-out visitor is redirected from the home page
- **Test Code:** [TC007](./TC007_Signed_out_visitor_is_redirected_from_the_home_page.py)
- **Test Visualization and Result:** https://www.testsprite.com/dashboard-v3/o/c09da5e8-63e9-5b6d-b467-be07561cc23c/projects/mcp/3c08f3f2-2601-59f0-aee7-c3f3391a7ce8/test/8eef2761-10ef-4abe-ac51-ac516d42d25f
- **Status:** ✅ Passed
- **Severity:** LOW
- **Analysis / Findings:** Redirects to /login.
---

#### Test TC008 Signed-out visitor is redirected from the deck builder
- **Test Code:** [TC008](./TC008_Signed_out_visitor_is_redirected_from_the_deck_builder.py)
- **Test Visualization and Result:** https://www.testsprite.com/dashboard-v3/o/c09da5e8-63e9-5b6d-b467-be07561cc23c/projects/mcp/3c08f3f2-2601-59f0-aee7-c3f3391a7ce8/test/50056a08-9ad0-46de-9654-4d62cb6c4087
- **Status:** ✅ Passed
- **Severity:** LOW
- **Analysis / Findings:** Redirects to /login.
---

#### Test TC009 Signed-out visitor is redirected from settings
- **Test Code:** [TC009](./TC009_Signed_out_visitor_is_redirected_from_settings.py)
- **Test Visualization and Result:** https://www.testsprite.com/dashboard-v3/o/c09da5e8-63e9-5b6d-b467-be07561cc23c/projects/mcp/3c08f3f2-2601-59f0-aee7-c3f3391a7ce8/test/eec3723f-e608-4a34-8958-04578e594ff0
- **Status:** ✅ Passed
- **Severity:** LOW
- **Analysis / Findings:** Redirects to /login.
---

### Requirement: Collection after signup
- **Description:** A new account's collection loads without the "Error loading database" toast.

#### Test TC013 Collection loads without an error toast after signup
- **Test Code:** [TC013](./TC013_Collection_loads_without_an_error_toast_after_signup.py)
- **Test Visualization and Result:** https://www.testsprite.com/dashboard-v3/o/c09da5e8-63e9-5b6d-b467-be07561cc23c/projects/mcp/3c08f3f2-2601-59f0-aee7-c3f3391a7ce8/test/a5ec4109-b4ba-4e41-bcb1-d3d779849e55
- **Status:** ✅ Passed
- **Severity:** LOW
- **Analysis / Findings:** No error toast appears. This confirms the language fix: `es` now falls back to `en`, because YGOPRODeck answered 400 for `es`.
---

#### Test TC015 Fresh collection load shows a loading state before cards appear
- **Test Code:** [TC015](./TC015_Fresh_collection_load_shows_a_loading_state_before_cards_appear.py)
- **Test Visualization and Result:** https://www.testsprite.com/dashboard-v3/o/c09da5e8-63e9-5b6d-b467-be07561cc23c/projects/mcp/3c08f3f2-2601-59f0-aee7-c3f3391a7ce8/test/5a539ead-8673-4249-94a2-b250df8e93ab
- **Status:** ✅ Passed (run 2). It was BLOCKED in run 1.
- **Severity:** LOW
- **Analysis / Findings:** With the card database cached, the load is too quick to show a loading state. Run 2 accepted an empty collection with no error.
---

## 3️⃣ Coverage & Matching Metrics

- **95% of tests passed** (19/20) after the login fix. Run 1 was 80% (16/20).

| Requirement              | Total Tests | ✅ Passed | ❌ Failed |
|--------------------------|-------------|-----------|-----------|
| Signup                   | 4           | 4         | 0         |
| Signup validation        | 4           | 4         | 0         |
| Login and session        | 4           | 3         | 1         |
| Route protection         | 6           | 6         | 0         |
| Collection after signup  | 2           | 2         | 0         |
| **Total**                | **20**      | **19**    | **1**     |

---

## 4️⃣ Key Gaps / Risks
- **Fixed during this run (HIGH):** the login button sent users to the signup request, so no existing user could sign in with the button. The fix is deployed to production and covered by a regression test.
- **TC010 is flaky:** it got a wrong-password error once through the TestSprite tunnel. It did not reproduce locally (10/10) or in production, and the test also expects the wrong URL after login.
- **No rate limit on /api/v1/register or login:** the only defence is a 1-second delay after a failed login. Mass account creation is possible.
- **Not covered:** password change, logout, account deletion, and the HTTPS/IIS WebSocket path. TestSprite ran against the local instance; the IIS path was checked separately with Playwright against https://tgoct.suils.es.
- **Not committed:** the fixes only exist on `features/mostrador-ui-973a` plus uncommitted changes. `main` has no signup.
